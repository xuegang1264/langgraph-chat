from uuid import uuid4
import json

from fastapi.testclient import TestClient
import pytest

from app.core.config import settings
from app.agent.groupGraph.node.common import asks_user_for_input
from app.main import create_app
from app.services import dashscope


@pytest.fixture(autouse=True)
def restore_settings():
    original_api_key = settings.dashscope_api_key
    original_base_url = settings.dashscope_base_url
    yield
    object.__setattr__(settings, "dashscope_api_key", original_api_key)
    object.__setattr__(settings, "dashscope_base_url", original_base_url)


def sse_events(body: str) -> list[tuple[str, dict]]:
    events = []
    for raw_event in body.strip().split("\n\n"):
        if not raw_event:
            continue
        lines = raw_event.splitlines()
        event_type = lines[0].removeprefix("event: ")
        event_data = json.loads(lines[1].removeprefix("data: "))
        events.append((event_type, event_data))
    return events


def test_chat_and_history_survive_restart(tmp_path) -> None:
    object.__setattr__(settings, "dashscope_api_key", None)
    thread_id = str(uuid4())
    sqlite_path = str(tmp_path / "checkpoints.sqlite")

    with TestClient(create_app(sqlite_path)) as client:
        chat_response = client.post(
            "/agent/chat",
            json={"thread_id": thread_id, "message": "你好"},
        )

    assert chat_response.status_code == 200
    assert sse_events(chat_response.text) == [("done", {"thread_id": thread_id})]

    with TestClient(create_app(sqlite_path)) as client:
        history_response = client.get(
            "/agent/history",
            params={"thread_id": thread_id},
        )

    assert history_response.status_code == 200
    assert history_response.json() == {
        "thread_id": thread_id,
        "messages": [{"role": "user", "content": "你好"}],
    }


def test_empty_history(tmp_path) -> None:
    object.__setattr__(settings, "dashscope_api_key", None)
    thread_id = str(uuid4())
    sqlite_path = str(tmp_path / "checkpoints.sqlite")

    with TestClient(create_app(sqlite_path)) as client:
        response = client.get("/agent/history", params={"thread_id": thread_id})

    assert response.status_code == 200
    assert response.json() == {"thread_id": thread_id, "messages": []}


def test_delete_chat_history_removes_checkpoint(tmp_path) -> None:
    object.__setattr__(settings, "dashscope_api_key", None)
    thread_id = str(uuid4())

    with TestClient(create_app(str(tmp_path / "checkpoints.sqlite"))) as client:
        chat_response = client.post(
            "/agent/chat",
            json={"thread_id": thread_id, "message": "你好"},
        )
        delete_response = client.delete(
            "/agent/history",
            params={"thread_id": thread_id},
        )
        history_response = client.get(
            "/agent/history",
            params={"thread_id": thread_id},
        )

    assert chat_response.status_code == 200
    assert delete_response.status_code == 200
    assert delete_response.json() == {"thread_id": thread_id}
    assert history_response.status_code == 200
    assert history_response.json() == {"thread_id": thread_id, "messages": []}


def test_dashscope_error_returns_bad_gateway(tmp_path, monkeypatch) -> None:
    object.__setattr__(settings, "dashscope_api_key", "test-key")

    async def fail_chat_stream(*args, **kwargs):
        raise dashscope.DashScopeError("InvalidApiKey", "Invalid API-key provided.", 401)
        yield

    monkeypatch.setattr(dashscope, "chat_stream", fail_chat_stream)

    with TestClient(create_app(str(tmp_path / "checkpoints.sqlite"))) as client:
        response = client.post(
            "/agent/chat",
            json={"thread_id": str(uuid4()), "message": "你好"},
        )

    assert response.status_code == 200
    assert sse_events(response.text) == [
        (
            "error",
            {"detail": "DashScope call failed: InvalidApiKey: Invalid API-key provided."},
        )
    ]


def test_dashscope_chat_uses_checkpoint_history(tmp_path, monkeypatch) -> None:
    object.__setattr__(settings, "dashscope_api_key", "test-key")
    object.__setattr__(settings, "dashscope_base_url", None)
    thread_id = str(uuid4())
    sqlite_path = str(tmp_path / "checkpoints.sqlite")
    captured_messages = []

    async def fake_chat_stream(*args, **kwargs):
        captured_messages.append(kwargs["messages"])
        reply = f"回复 {len(captured_messages)}"
        for token in ("回复 ", str(len(captured_messages))):
            yield token

    monkeypatch.setattr(dashscope, "chat_stream", fake_chat_stream)

    with TestClient(create_app(sqlite_path)) as client:
        first_response = client.post(
            "/agent/chat",
            json={"thread_id": thread_id, "message": "第一句"},
        )
        second_response = client.post(
            "/agent/chat",
            json={"thread_id": thread_id, "message": "第二句"},
        )
        history_response = client.get(
            "/agent/history",
            params={"thread_id": thread_id},
        )

    assert first_response.status_code == 200
    assert second_response.status_code == 200
    assert sse_events(first_response.text) == [
        ("token", {"token": "回复 "}),
        ("token", {"token": "1"}),
        ("message", {"role": "assistant", "content": "回复 1"}),
        ("done", {"thread_id": thread_id}),
    ]
    assert sse_events(second_response.text) == [
        ("token", {"token": "回复 "}),
        ("token", {"token": "2"}),
        ("message", {"role": "assistant", "content": "回复 2"}),
        ("done", {"thread_id": thread_id}),
    ]
    assert captured_messages == [
        [{"role": "user", "content": "第一句"}],
        [
            {"role": "user", "content": "第一句"},
            {"role": "assistant", "content": "回复 1"},
            {"role": "user", "content": "第二句"},
        ],
    ]
    assert history_response.json() == {
        "thread_id": thread_id,
        "messages": [
            {"role": "user", "content": "第一句"},
            {"role": "assistant", "content": "回复 1"},
            {"role": "user", "content": "第二句"},
            {"role": "assistant", "content": "回复 2"},
        ],
    }


def test_group_chat_routes_roles_and_saves_checkpoint(tmp_path, monkeypatch) -> None:
    object.__setattr__(settings, "dashscope_api_key", "test-key")
    object.__setattr__(settings, "dashscope_base_url", None)
    thread_id = str(uuid4())
    captured_calls = []

    async def fake_chat(*args, **kwargs) -> str:
        captured_calls.append(kwargs["messages"])
        system_prompt = kwargs["messages"][0]["content"]
        if "群聊发言调度" in system_prompt:
            return (
                '{"action":"continue","next_role":"产品经理",'
                '"reason":"需要先明确需求"}'
            )
        return (
            '{"content":"我先把需求边界和用户价值梳理清楚。",'
            '"should_continue":false,"next_role":""}'
        )

    monkeypatch.setattr(dashscope, "chat", fake_chat)

    with TestClient(create_app(str(tmp_path / "checkpoints.sqlite"))) as client:
        response = client.post(
            "/group-chat/chat",
            json={
                "thread_id": thread_id,
                "message": "这个功能怎么做？",
                "user_persona": "我是老板，关注投入产出比",
                "members": [
                    {
                        "name": "产品经理",
                        "persona": "关注用户需求和方案边界",
                    },
                    {
                        "name": "后端开发",
                        "persona": "关注接口和数据存储",
                    },
                ],
                "max_rounds": 1,
            },
        )
        history_response = client.get(
            "/group-chat/history",
            params={"thread_id": thread_id},
        )

    assert response.status_code == 200
    assert response.json() == {
        "thread_id": thread_id,
        "messages": [
            {
                "role": "assistant",
                "content": "我先把需求边界和用户价值梳理清楚。",
                "name": "产品经理",
            }
        ],
    }
    assert history_response.json() == {
        "thread_id": thread_id,
        "messages": [
            {"role": "user", "content": "这个功能怎么做？"},
            {
                "role": "assistant",
                "content": "我先把需求边界和用户价值梳理清楚。",
                "name": "产品经理",
            },
        ],
    }


def test_delete_group_chat_history_removes_checkpoint(tmp_path) -> None:
    object.__setattr__(settings, "dashscope_api_key", None)
    thread_id = str(uuid4())

    with TestClient(create_app(str(tmp_path / "checkpoints.sqlite"))) as client:
        chat_response = client.post(
            "/group-chat/chat",
            json={
                "thread_id": thread_id,
                "message": "这个功能怎么做？",
                "members": [{"name": "产品经理", "persona": "关注需求"}],
            },
        )
        delete_response = client.delete(
            "/group-chat/history",
            params={"thread_id": thread_id},
        )
        history_response = client.get(
            "/group-chat/history",
            params={"thread_id": thread_id},
        )

    assert chat_response.status_code == 200
    assert delete_response.status_code == 200
    assert delete_response.json() == {"thread_id": thread_id}
    assert history_response.status_code == 200
    assert history_response.json() == {"thread_id": thread_id, "messages": []}


def test_group_chat_streams_each_role_node(tmp_path, monkeypatch) -> None:
    object.__setattr__(settings, "dashscope_api_key", "test-key")
    object.__setattr__(settings, "dashscope_base_url", None)
    thread_id = str(uuid4())
    router_calls = 0

    async def fake_chat(*args, **kwargs) -> str:
        nonlocal router_calls
        system_prompt = kwargs["messages"][0]["content"]
        if "群聊发言调度" in system_prompt:
            router_calls += 1
            return (
                '{"action":"continue","next_role":"产品经理",'
                '"reason":"先定范围，再看实现"}'
            )

        if "你是群聊中的产品经理" in system_prompt:
            return (
                '{"content":"先明确需求范围。",'
                '"should_continue":true,"next_role":"后端开发"}'
            )
        return '{"content":"接口和存储可以这样拆。","should_continue":false,"next_role":""}'

    monkeypatch.setattr(dashscope, "chat", fake_chat)

    with TestClient(create_app(str(tmp_path / "checkpoints.sqlite"))) as client:
        with client.stream(
            "POST",
            "/group-chat/chat/stream",
            json={
                "thread_id": thread_id,
                "message": "这个功能怎么做？",
                "members": [
                    {"name": "产品经理", "persona": "关注需求"},
                    {"name": "后端开发", "persona": "关注接口"},
                ],
                "max_rounds": 2,
            },
        ) as response:
            body = response.read().decode()

        history_response = client.get(
            "/group-chat/history",
            params={"thread_id": thread_id},
        )

    events = sse_events(body)

    assert response.status_code == 200
    assert router_calls == 1
    assert events == [
        (
            "message",
            {"role": "assistant", "content": "先明确需求范围。", "name": "产品经理"},
        ),
        (
            "message",
            {
                "role": "assistant",
                "content": "接口和存储可以这样拆。",
                "name": "后端开发",
            },
        ),
        ("done", {"thread_id": thread_id}),
    ]
    assert history_response.json() == {
        "thread_id": thread_id,
        "messages": [
            {"role": "user", "content": "这个功能怎么做？"},
            {"role": "assistant", "content": "先明确需求范围。", "name": "产品经理"},
            {
                "role": "assistant",
                "content": "接口和存储可以这样拆。",
                "name": "后端开发",
            },
        ],
    }


def test_group_chat_role_selects_next_speaker_without_router(tmp_path, monkeypatch) -> None:
    object.__setattr__(settings, "dashscope_api_key", "test-key")
    object.__setattr__(settings, "dashscope_base_url", None)
    thread_id = str(uuid4())
    router_calls = 0

    async def fake_chat(*args, **kwargs) -> str:
        nonlocal router_calls
        system_prompt = kwargs["messages"][0]["content"]
        if "群聊发言调度" in system_prompt:
            router_calls += 1
            return (
                '{"action":"continue","next_role":"产品经理",'
                '"reason":"先定需求再看实现"}'
            )

        if "你是群聊中的产品经理" in system_prompt:
            return (
                '{"content":"需求里有跨系统一致性风险，需要先让架构师评估。",'
                '"should_continue":true,"next_role":"架构师"}'
            )
        return '{"content":"这里要先确认服务边界和一致性策略。","should_continue":false,"next_role":""}'

    monkeypatch.setattr(dashscope, "chat", fake_chat)

    with TestClient(create_app(str(tmp_path / "checkpoints.sqlite"))) as client:
        response = client.post(
            "/group-chat/chat",
            json={
                "thread_id": thread_id,
                "message": "这个功能怎么做？",
                "members": [
                    {"name": "产品经理", "persona": "关注需求"},
                    {"name": "后端开发", "persona": "关注接口"},
                    {"name": "架构师", "persona": "关注架构风险"},
                ],
                "max_rounds": 2,
            },
        )

    assert response.status_code == 200
    assert router_calls == 1
    assert response.json() == {
        "thread_id": thread_id,
        "messages": [
            {
                "role": "assistant",
                "content": "需求里有跨系统一致性风险，需要先让架构师评估。",
                "name": "产品经理",
            },
            {
                "role": "assistant",
                "content": "这里要先确认服务边界和一致性策略。",
                "name": "架构师",
            },
        ],
    }


def test_group_chat_stops_when_role_asks_user_for_input(tmp_path, monkeypatch) -> None:
    object.__setattr__(settings, "dashscope_api_key", "test-key")
    object.__setattr__(settings, "dashscope_base_url", None)
    thread_id = str(uuid4())
    role_calls = []

    async def fake_chat(*args, **kwargs) -> str:
        system_prompt = kwargs["messages"][0]["content"]
        if "群聊发言调度" in system_prompt:
            return (
                '{"action":"continue","next_role":"产品经理",'
                '"reason":"先让产品接话"}'
            )

        if "你是群聊中的产品经理" in system_prompt:
            role_calls.append("产品经理")
            return (
                '{"content":"群主先给个主题吧，要解决什么问题？",'
                '"should_continue":true,"next_role":"后端开发"}'
            )

        role_calls.append("后端开发")
        return '{"content":"我也想问下接口范围。","should_continue":false,"next_role":""}'

    monkeypatch.setattr(dashscope, "chat", fake_chat)

    with TestClient(create_app(str(tmp_path / "checkpoints.sqlite"))) as client:
        response = client.post(
            "/group-chat/chat",
            json={
                "thread_id": thread_id,
                "message": "大家自由讨论",
                "members": [
                    {"name": "产品经理", "persona": "关注需求"},
                    {"name": "后端开发", "persona": "关注接口"},
                ],
                "max_rounds": 5,
            },
        )

    assert response.status_code == 200
    assert role_calls == ["产品经理"]
    assert response.json() == {
        "thread_id": thread_id,
        "messages": [
            {
                "role": "assistant",
                "content": "群主先给个主题吧，要解决什么问题？",
                "name": "产品经理",
            }
        ],
    }


@pytest.mark.parametrize(
    "content",
    [
        "你看，需求这东西每次都变，真离谱？",
        "你看需求是什么鬼？这不就是反复横跳吗？",
        "老板之前告诉我们预算别太离谱，这事挺现实的。",
        "我先把需求范围说下，大家继续补充。",
    ],
)
def test_asks_user_for_input_ignores_loose_keyword_matches(content: str) -> None:
    assert asks_user_for_input(content) is False


@pytest.mark.parametrize(
    "content",
    [
        "群主先给个主题吧，要解决什么问题？",
        "麻烦你确认下预算和时间。",
        "老板方便补充一下背景信息吗？",
    ],
)
def test_asks_user_for_input_detects_direct_user_requests(content: str) -> None:
    assert asks_user_for_input(content) is True


def test_group_chat_keeps_discussing_before_minimum_rounds(tmp_path, monkeypatch) -> None:
    object.__setattr__(settings, "dashscope_api_key", "test-key")
    object.__setattr__(settings, "dashscope_base_url", None)
    thread_id = str(uuid4())
    role_calls = []

    async def fake_chat(*args, **kwargs) -> str:
        system_prompt = kwargs["messages"][0]["content"]
        if "群聊发言调度" in system_prompt:
            return (
                '{"action":"continue","next_role":"产品经理",'
                '"reason":"先让产品接话"}'
            )

        if "你是群聊中的产品经理" in system_prompt:
            role_calls.append("产品经理")
            return '{"content":"我选方案1，轻松自由。","should_continue":false,"next_role":""}'

        role_calls.append("后端开发")
        return '{"content":"我也选方案1，别安排太满。","should_continue":false,"next_role":""}'

    monkeypatch.setattr(dashscope, "chat", fake_chat)

    with TestClient(create_app(str(tmp_path / "checkpoints.sqlite"))) as client:
        response = client.post(
            "/group-chat/chat",
            json={
                "thread_id": thread_id,
                "message": "其他人从1和3里选一个",
                "members": [
                    {"name": "产品经理", "persona": "关注需求"},
                    {"name": "后端开发", "persona": "关注接口"},
                ],
                "max_rounds": 4,
            },
        )

    assert response.status_code == 200
    assert role_calls == ["产品经理", "后端开发", "产品经理", "后端开发"]
    assert response.json() == {
        "thread_id": thread_id,
        "messages": [
            {"role": "assistant", "content": "我选方案1，轻松自由。", "name": "产品经理"},
            {"role": "assistant", "content": "我也选方案1，别安排太满。", "name": "后端开发"},
            {"role": "assistant", "content": "我选方案1，轻松自由。", "name": "产品经理"},
            {"role": "assistant", "content": "我也选方案1，别安排太满。", "name": "后端开发"},
        ],
    }

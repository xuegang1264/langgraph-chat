from uuid import uuid4
import json

from fastapi.testclient import TestClient
import pytest

from app.core.config import settings
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
                '{"action":"continue","role_sequence":["产品经理"],'
                '"reason":"需要先明确需求"}'
            )
        return (
            '{"content":"我先把需求边界和用户价值梳理清楚。",'
            '"need_replan":false,"replan_reason":""}'
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
                "max_rounds": 3,
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
                '{"action":"continue","role_sequence":["产品经理","后端开发"],'
                '"reason":"先定范围，再看实现"}'
            )

        if "你是群聊中的产品经理" in system_prompt:
            return '{"content":"先明确需求范围。","need_replan":false,"replan_reason":""}'
        return '{"content":"接口和存储可以这样拆。","need_replan":false,"replan_reason":""}'

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
                "max_rounds": 3,
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


def test_group_chat_replans_after_role_request(tmp_path, monkeypatch) -> None:
    object.__setattr__(settings, "dashscope_api_key", "test-key")
    object.__setattr__(settings, "dashscope_base_url", None)
    thread_id = str(uuid4())
    router_calls = 0

    async def fake_chat(*args, **kwargs) -> str:
        nonlocal router_calls
        system_prompt = kwargs["messages"][0]["content"]
        if "群聊发言调度" in system_prompt:
            router_calls += 1
            if router_calls == 1:
                return (
                    '{"action":"continue","role_sequence":["产品经理","后端开发"],'
                    '"reason":"先定需求再看实现"}'
                )
            return (
                '{"action":"continue","role_sequence":["架构师"],'
                '"reason":"需要先评估架构风险"}'
            )

        if "你是群聊中的产品经理" in system_prompt:
            return (
                '{"content":"需求里有跨系统一致性风险，需要先让架构师评估。",'
                '"need_replan":true,"replan_reason":"存在架构风险，架构师应先介入"}'
            )
        return '{"content":"这里要先确认服务边界和一致性策略。","need_replan":false,"replan_reason":""}'

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
                "max_rounds": 3,
            },
        )

    assert response.status_code == 200
    assert router_calls == 2
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

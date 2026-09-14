from uuid import uuid4

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
    assert chat_response.json() == {
        "thread_id": thread_id,
        "message": {"role": "user", "content": "你好"},
    }

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


def test_dashscope_error_returns_bad_gateway(tmp_path, monkeypatch) -> None:
    object.__setattr__(settings, "dashscope_api_key", "test-key")

    async def fail_chat(*args, **kwargs) -> str:
        raise dashscope.DashScopeError("InvalidApiKey", "Invalid API-key provided.", 401)

    monkeypatch.setattr(dashscope, "chat", fail_chat)

    with TestClient(create_app(str(tmp_path / "checkpoints.sqlite"))) as client:
        response = client.post(
            "/agent/chat",
            json={"thread_id": str(uuid4()), "message": "你好"},
        )

    assert response.status_code == 502
    assert response.json() == {
        "detail": "DashScope call failed: InvalidApiKey: Invalid API-key provided."
    }


def test_dashscope_chat_uses_checkpoint_history(tmp_path, monkeypatch) -> None:
    object.__setattr__(settings, "dashscope_api_key", "test-key")
    object.__setattr__(settings, "dashscope_base_url", None)
    thread_id = str(uuid4())
    sqlite_path = str(tmp_path / "checkpoints.sqlite")
    captured_messages = []

    async def fake_chat(*args, **kwargs) -> str:
        captured_messages.append(kwargs["messages"])
        return f"回复 {len(captured_messages)}"

    monkeypatch.setattr(dashscope, "chat", fake_chat)

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

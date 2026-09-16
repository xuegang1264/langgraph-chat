import asyncio

import httpx

from app.services import dashscope
from app.services.dashscope import clean_model_content


def test_clean_model_content_removes_safety_tag() -> None:
    content = (
        "<ds_safety>[用户未成年]否 [分类]其他 "
        "[判定]内容为技术方案讨论。 [规则]无</ds_safety>Safe"
        "可以先拆成前端、后端和测试三个任务。"
    )

    assert clean_model_content(content) == "可以先拆成前端、后端和测试三个任务。"


def test_clean_model_content_keeps_normal_reply() -> None:
    assert clean_model_content("正常回复") == "正常回复"


def test_openai_compatible_stream_skips_empty_choices(monkeypatch) -> None:
    original_async_client = httpx.AsyncClient

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=(
                'data: {"choices":[]}\n\n'
                'data: {"choices":[{"delta":{"content":"你"}}]}\n\n'
                'data: {"choices":[{"delta":{"content":"好"}}]}\n\n'
                "data: [DONE]\n\n"
            ),
        )

    def client_factory(*args, **kwargs):
        return original_async_client(transport=httpx.MockTransport(handler))

    monkeypatch.setattr(dashscope.httpx, "AsyncClient", client_factory)

    async def collect() -> list[str]:
        return [
            token
            async for token in dashscope._chat_stream_openai_compatible(
                api_key="test-key",
                base_url="https://example.com/v1",
                model="test-model",
                messages=[{"role": "user", "content": "你好"}],
            )
        ]

    assert asyncio.run(collect()) == ["你", "好"]

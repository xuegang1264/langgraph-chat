import asyncio

from app.services import tokenplan
from app.services.tokenplan import clean_model_content


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
    class FakeDelta:
        def __init__(self, content: str | None = None) -> None:
            self.content = content

    class FakeChoice:
        def __init__(self, content: str) -> None:
            self.delta = FakeDelta(content)

    class FakeChunk:
        def __init__(self, choices) -> None:
            self.choices = choices

    class FakeStream:
        def __init__(self) -> None:
            self.chunks = iter(
                [
                    FakeChunk([]),
                    FakeChunk([FakeChoice("你")]),
                    FakeChunk([FakeChoice("好")]),
                ]
            )

        def __aiter__(self):
            return self

        async def __anext__(self):
            try:
                return next(self.chunks)
            except StopIteration as exc:
                raise StopAsyncIteration from exc

    class FakeCompletions:
        async def create(self, **kwargs):
            return FakeStream()

    class FakeChat:
        completions = FakeCompletions()

    class FakeClient:
        chat = FakeChat()

    monkeypatch.setattr(tokenplan, "_client", lambda *args, **kwargs: FakeClient())

    async def collect() -> list[str]:
        return [
            token
            async for token in tokenplan.chat_stream(
                thread_id="test-thread",
                api_key="test-key",
                base_url="https://example.com/v1",
                model="test-model",
                messages=[{"role": "user", "content": "你好"}],
            )
        ]

    assert asyncio.run(collect()) == ["你", "好"]

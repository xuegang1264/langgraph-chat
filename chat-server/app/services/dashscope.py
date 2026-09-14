import asyncio
import os

from dashscope import Generation
import httpx


TOKEN_PLAN_BASE_URL = "https://token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1"


class DashScopeError(RuntimeError):
    def __init__(self, code: str, message: str, status_code: int | None = None) -> None:
        super().__init__(f"DashScope error {code}: {message}")
        self.code = code
        self.message = message
        self.status_code = status_code


async def chat(
    thread_id: str,
    messages: list[dict[str, str]],
    model: str = "qwen-plus",
    api_key: str | None = None,
    base_url: str | None = None,
) -> str:
    """Call DashScope (Bailian) chat model and return the assistant's reply."""
    api_key = api_key or os.getenv("DASHSCOPE_API_KEY")
    if not api_key:
        raise DashScopeError("MissingApiKey", "DASHSCOPE_API_KEY is not set")

    if base_url or api_key.startswith("sk-sp-"):
        return await _chat_openai_compatible(
            api_key=api_key,
            base_url=base_url or TOKEN_PLAN_BASE_URL,
            model=model,
            messages=messages,
        )

    def _call():
        return Generation.call(
            api_key=api_key,
            model=model,
            messages=messages,
            result_format="message",
        )

    response = await asyncio.to_thread(_call)

    if response.status_code != 200:
        raise DashScopeError(response.code, response.message, response.status_code)

    return response.output.choices[0].message.content


async def _chat_openai_compatible(
    api_key: str,
    base_url: str,
    model: str,
    messages: list[dict[str, str]],
) -> str:
    url = f"{base_url.rstrip('/')}/chat/completions"
    payload = {"model": model, "messages": messages}
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post(url, json=payload, headers=headers)

    try:
        data = response.json()
    except ValueError as exc:
        raise DashScopeError(
            f"HTTP{response.status_code}",
            response.text,
            response.status_code,
        ) from exc

    if response.status_code != 200:
        error = data.get("error", data)
        raise DashScopeError(
            str(error.get("code", f"HTTP{response.status_code}")),
            str(error.get("message", response.text)),
            response.status_code,
        )

    return data["choices"][0]["message"]["content"]

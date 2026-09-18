import asyncio
from collections.abc import AsyncIterator
import json
import os
import re
from typing import Any

from dashscope import Generation
import httpx


TOKEN_PLAN_BASE_URL = "https://token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1"
SAFETY_TAG_PATTERN = re.compile(r"<ds_safety>.*?</ds_safety>\s*(?:Safe\s*)?", re.DOTALL)


class DashScopeError(RuntimeError):
    def __init__(self, code: str, message: str, status_code: int | None = None) -> None:
        super().__init__(f"DashScope error {code}: {message}")
        self.code = code
        self.message = message
        self.status_code = status_code


def clean_model_content(content: str) -> str:
    return SAFETY_TAG_PATTERN.sub("", content).strip()


def _to_plain(value):
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, list | tuple):
        return [_to_plain(item) for item in value]
    if isinstance(value, dict):
        return {key: _to_plain(item) for key, item in value.items() if item is not None}
    if hasattr(value, "model_dump"):
        return _to_plain(value.model_dump())
    if hasattr(value, "to_dict"):
        return _to_plain(value.to_dict())
    if hasattr(value, "__dict__"):
        return {
            key: _to_plain(item)
            for key, item in vars(value).items()
            if not key.startswith("_") and item is not None
        }
    return value


def _normalize_assistant_message(message) -> dict[str, Any]:
    data = _to_plain(message)
    if not isinstance(data, dict):
        return {"role": "assistant", "content": clean_model_content(str(data))}

    content = data.get("content")
    normalized = {
        "role": data.get("role") or "assistant",
        "content": clean_model_content(content) if isinstance(content, str) else content,
    }
    if data.get("tool_calls"):
        normalized["tool_calls"] = data["tool_calls"]
    return {key: value for key, value in normalized.items() if value is not None}


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

    return clean_model_content(response.output.choices[0].message.content)


async def chat_completion(
    thread_id: str,
    messages: list[dict[str, Any]],
    model: str = "qwen-plus",
    api_key: str | None = None,
    base_url: str | None = None,
    tools: list[dict[str, Any]] | None = None,
    tool_choice: str | dict[str, Any] | None = "auto",
) -> dict[str, Any]:
    """Call DashScope chat model and return the complete assistant message."""
    api_key = api_key or os.getenv("DASHSCOPE_API_KEY")
    if not api_key:
        raise DashScopeError("MissingApiKey", "DASHSCOPE_API_KEY is not set")

    if base_url or api_key.startswith("sk-sp-"):
        return await _chat_completion_openai_compatible(
            api_key=api_key,
            base_url=base_url or TOKEN_PLAN_BASE_URL,
            model=model,
            messages=messages,
            tools=tools,
            tool_choice=tool_choice,
        )

    def _call():
        kwargs = {
            "api_key": api_key,
            "model": model,
            "messages": messages,
            "result_format": "message",
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = tool_choice or "auto"
        return Generation.call(**kwargs)

    response = await asyncio.to_thread(_call)

    if response.status_code != 200:
        raise DashScopeError(response.code, response.message, response.status_code)

    return _normalize_assistant_message(response.output.choices[0].message)


async def chat_stream(
    thread_id: str,
    messages: list[dict[str, str]],
    model: str = "qwen-plus",
    api_key: str | None = None,
    base_url: str | None = None,
) -> AsyncIterator[str]:
    """Call DashScope (Bailian) chat model and yield assistant reply chunks."""
    api_key = api_key or os.getenv("DASHSCOPE_API_KEY")
    if not api_key:
        raise DashScopeError("MissingApiKey", "DASHSCOPE_API_KEY is not set")

    if base_url or api_key.startswith("sk-sp-"):
        async for chunk in _chat_stream_openai_compatible(
            api_key=api_key,
            base_url=base_url or TOKEN_PLAN_BASE_URL,
            model=model,
            messages=messages,
        ):
            yield chunk
        return

    def _call():
        return Generation.call(
            api_key=api_key,
            model=model,
            messages=messages,
            result_format="message",
            stream=True,
            incremental_output=True,
        )

    responses = await asyncio.to_thread(_call)

    while True:
        response = await asyncio.to_thread(next, responses, None)
        if response is None:
            break

        if response.status_code != 200:
            raise DashScopeError(response.code, response.message, response.status_code)

        content = response.output.choices[0].message.content
        if content:
            yield content


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

    return clean_model_content(data["choices"][0]["message"]["content"])


async def _chat_completion_openai_compatible(
    api_key: str,
    base_url: str,
    model: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None = None,
    tool_choice: str | dict[str, Any] | None = "auto",
) -> dict[str, Any]:
    url = f"{base_url.rstrip('/')}/chat/completions"
    payload: dict[str, Any] = {"model": model, "messages": messages}
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = tool_choice or "auto"
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

    return _normalize_assistant_message(data["choices"][0]["message"])


async def _chat_stream_openai_compatible(
    api_key: str,
    base_url: str,
    model: str,
    messages: list[dict[str, str]],
) -> AsyncIterator[str]:
    url = f"{base_url.rstrip('/')}/chat/completions"
    payload = {"model": model, "messages": messages, "stream": True}
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=60) as client:
        async with client.stream("POST", url, json=payload, headers=headers) as response:
            if response.status_code != 200:
                error_text = await response.aread()
                try:
                    data = json.loads(error_text)
                    error = data.get("error", data)
                    code = str(error.get("code", f"HTTP{response.status_code}"))
                    message = str(error.get("message", error_text.decode()))
                except (ValueError, UnicodeDecodeError):
                    code = f"HTTP{response.status_code}"
                    message = error_text.decode(errors="replace")
                raise DashScopeError(code, message, response.status_code)

            async for line in response.aiter_lines():
                if not line.startswith("data:"):
                    continue

                raw = line.removeprefix("data:").strip()
                if not raw:
                    continue
                if raw == "[DONE]":
                    break

                try:
                    data = json.loads(raw)
                except ValueError:
                    continue

                choices = data.get("choices") or []
                if not choices:
                    continue

                choice = choices[0]
                delta = choice.get("delta") or {}
                message = choice.get("message") or {}
                content = delta.get("content") or message.get("content")
                if content:
                    yield content

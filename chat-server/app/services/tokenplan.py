from collections.abc import AsyncIterator
import os
import re
from typing import Any

from openai import APIConnectionError, APIStatusError, APITimeoutError, AsyncOpenAI, OpenAIError


TOKENPLAN_BASE_URL = "https://token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1"
SAFETY_TAG_PATTERN = re.compile(r"<ds_safety>.*?</ds_safety>\s*(?:Safe\s*)?", re.DOTALL)


class TokenPlanError(RuntimeError):
    def __init__(self, code: str, message: str, status_code: int | None = None) -> None:
        super().__init__(f"TokenPlan error {code}: {message}")
        self.code = code
        self.message = message
        self.status_code = status_code


def clean_model_content(content: str) -> str:
    return SAFETY_TAG_PATTERN.sub("", content).strip()


def _resolved_api_key(api_key: str | None) -> str:
    resolved = api_key or os.getenv("TOKENPLAN_API_KEY")
    if not resolved:
        raise TokenPlanError("MissingApiKey", "TOKENPLAN_API_KEY is not set")
    return resolved


def _resolved_base_url(base_url: str | None) -> str:
    if base_url:
        return base_url
    return TOKENPLAN_BASE_URL


def _client(api_key: str, base_url: str | None) -> AsyncOpenAI:
    return AsyncOpenAI(
        api_key=api_key,
        base_url=_resolved_base_url(base_url),
        timeout=60,
    )


def _to_plain(value: Any) -> Any:
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, list | tuple):
        return [_to_plain(item) for item in value]
    if isinstance(value, dict):
        return {key: _to_plain(item) for key, item in value.items() if item is not None}
    if hasattr(value, "model_dump"):
        return _to_plain(value.model_dump())
    return value


def _normalize_assistant_message(message: Any) -> dict[str, Any]:
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


def _raise_tokenplan_error(exc: OpenAIError) -> None:
    if isinstance(exc, APIStatusError):
        error = exc.response.json().get("error", {}) if exc.response is not None else {}
        code = str(error.get("code") or f"HTTP{exc.status_code}")
        message = str(error.get("message") or exc.message)
        raise TokenPlanError(code, message, exc.status_code) from exc
    if isinstance(exc, APITimeoutError):
        raise TokenPlanError("Timeout", str(exc), None) from exc
    if isinstance(exc, APIConnectionError):
        raise TokenPlanError("ConnectionError", str(exc), None) from exc
    raise TokenPlanError(type(exc).__name__, str(exc), None) from exc


async def chat(
    thread_id: str,
    messages: list[dict[str, str]],
    model: str = "qwen-plus",
    api_key: str | None = None,
    base_url: str | None = None,
) -> str:
    """Call a Bailian OpenAI-compatible chat model and return assistant text."""
    resolved_api_key = _resolved_api_key(api_key)
    try:
        response = await _client(resolved_api_key, base_url).chat.completions.create(
            model=model,
            messages=messages,
        )
    except OpenAIError as exc:
        _raise_tokenplan_error(exc)

    return clean_model_content(response.choices[0].message.content or "")


async def chat_completion(
    thread_id: str,
    messages: list[dict[str, Any]],
    model: str = "qwen-plus",
    api_key: str | None = None,
    base_url: str | None = None,
    tools: list[dict[str, Any]] | None = None,
    tool_choice: str | dict[str, Any] | None = "auto",
) -> dict[str, Any]:
    """Call a Bailian OpenAI-compatible chat model and return assistant message."""
    resolved_api_key = _resolved_api_key(api_key)
    kwargs: dict[str, Any] = {
        "model": model,
        "messages": messages,
    }
    if tools:
        kwargs["tools"] = tools
        kwargs["tool_choice"] = tool_choice or "auto"

    try:
        response = await _client(resolved_api_key, base_url).chat.completions.create(**kwargs)
    except OpenAIError as exc:
        _raise_tokenplan_error(exc)

    return _normalize_assistant_message(response.choices[0].message)


async def chat_stream(
    thread_id: str,
    messages: list[dict[str, str]],
    model: str = "qwen-plus",
    api_key: str | None = None,
    base_url: str | None = None,
) -> AsyncIterator[str]:
    """Call a Bailian OpenAI-compatible chat model and yield assistant tokens."""
    resolved_api_key = _resolved_api_key(api_key)
    try:
        stream = await _client(resolved_api_key, base_url).chat.completions.create(
            model=model,
            messages=messages,
            stream=True,
        )
        async for chunk in stream:
            if not chunk.choices:
                continue
            content = chunk.choices[0].delta.content
            if content:
                yield content
    except OpenAIError as exc:
        _raise_tokenplan_error(exc)

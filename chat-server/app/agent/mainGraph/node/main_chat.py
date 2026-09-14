from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.runnables import RunnableConfig

from app.core.config import settings
from app.services import dashscope


def _to_model_message(message: BaseMessage) -> dict[str, str] | None:
    if message.type == "human":
        role = "user"
    elif message.type == "ai":
        role = "assistant"
    elif message.type == "system":
        role = "system"
    else:
        return None

    return {"role": role, "content": str(message.content)}


async def main_chat_node(state: dict[str, Any], config: RunnableConfig) -> dict[str, Any]:
    current_message = str(state.get("current_message", "")).strip()
    if not current_message:
        return {}

    user_message = HumanMessage(content=current_message)
    if not settings.dashscope_api_key:
        return {"messages": [user_message]}

    history_messages = state.get("messages", [])
    messages = [
        model_message
        for message in history_messages
        if (model_message := _to_model_message(message)) is not None
    ]
    messages.append({"role": "user", "content": current_message})

    content = await dashscope.chat(
        thread_id=str(config.get("configurable", {}).get("thread_id", "")),
        messages=messages,
        model=settings.dashscope_model,
        api_key=settings.dashscope_api_key,
        base_url=settings.dashscope_base_url,
    )

    return {"messages": [user_message, AIMessage(content=content)]}

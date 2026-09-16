import json
import logging
import re
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.runnables import RunnableConfig

from app.core.config import settings
from app.services import dashscope


logger = logging.getLogger(__name__)


ROLE_NODE_BY_NAME = {
    "产品经理": "product_manager",
    "项目经理": "project_manager",
    "PMO": "pmo",
    "后端开发": "backend_dev",
    "前端开发": "frontend_dev",
    "测试工程师": "tester",
    "架构师": "architect",
    "业务负责人": "business_owner",
}


def get_thread_id(config: RunnableConfig) -> str:
    return str(config.get("configurable", {}).get("thread_id", ""))


def member_names(state: dict[str, Any]) -> list[str]:
    return [member["name"] for member in state.get("members", []) if member.get("name")]


def find_member(state: dict[str, Any], role_name: str) -> dict[str, str]:
    for member in state.get("members", []):
        if member.get("name") == role_name:
            return {"name": member.get("name", ""), "persona": member.get("persona", "")}
    return {"name": role_name, "persona": ""}


def to_model_message(message: BaseMessage) -> dict[str, str] | None:
    if message.type == "human":
        return {"role": "user", "content": str(message.content)}
    if message.type == "ai":
        name = getattr(message, "name", None)
        content = f"{name}: {message.content}" if name else str(message.content)
        return {"role": "assistant", "content": content}
    if message.type == "system":
        return {"role": "system", "content": str(message.content)}
    return None


def history_for_model(state: dict[str, Any], limit: int = 20) -> list[dict[str, str]]:
    messages = [
        model_message
        for message in state.get("messages", [])
        if (model_message := to_model_message(message)) is not None
    ]
    return messages[-limit:]


def parse_json_object(content: str) -> dict[str, Any]:
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", content, flags=re.DOTALL)
        if not match:
            return {}
        try:
            parsed = json.loads(match.group(0))
        except json.JSONDecodeError:
            return {}

    return parsed if isinstance(parsed, dict) else {}


async def call_llm(
    thread_id: str,
    messages: list[dict[str, str]],
    model: str | None = None,
) -> str:
    return await dashscope.chat(
        thread_id=thread_id,
        messages=messages,
        model=model or settings.dashscope_model,
        api_key=settings.dashscope_api_key,
        base_url=settings.dashscope_base_url,
    )


async def run_role_node(
    state: dict[str, Any],
    config: RunnableConfig,
    role_name: str,
) -> dict[str, Any]:
    round_count = int(state.get("round_count") or 0)
    spoken_roles = list(state.get("spoken_roles") or [])
    member = find_member(state, role_name)
    user_persona = str(state.get("user_persona") or "未设置")
    thread_id = get_thread_id(config)

    system_prompt = (
        f"你是群聊中的{role_name}。\n"
        f"你的角色人设：{member['persona'] or '按该岗位的专业职责发言'}。\n"
        f"用户在群聊中的身份/人设：{user_persona}。\n"
        "请只代表你自己的角色发言，结合上下文给出具体、简洁、有推进价值的回复。"
        "不要替其他角色总结，不要输出角色名前缀。"
    )
    messages = [{"role": "system", "content": system_prompt}]
    messages.extend(history_for_model(state))

    if not settings.dashscope_api_key:
        content = f"我是{role_name}，当前还没有配置可用的模型调用密钥。"
    else:
        logger.info(
            "Group chat role LLM request: thread_id=%s role_name=%s model=%s messages=%s",
            thread_id,
            role_name,
            settings.dashscope_model,
            messages,
        )
        content = await call_llm(thread_id=thread_id, messages=messages)

    if role_name not in spoken_roles:
        spoken_roles.append(role_name)

    return {
        "messages": [AIMessage(content=content, name=role_name)],
        "spoken_roles": spoken_roles,
        "round_count": round_count + 1,
    }

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

USER_REFERENCE_WORDS = ("群主", "用户", "你", "您", "老板", "业务方")
USER_INPUT_WORDS = (
    "给",
    "说",
    "确认",
    "明确",
    "补充",
    "提供",
    "告诉",
    "定",
    "透个底",
    "回复",
)


def get_thread_id(config: RunnableConfig) -> str:
    return str(config.get("configurable", {}).get("thread_id", ""))


def member_names(state: dict[str, Any]) -> list[str]:
    return [member["name"] for member in state.get("members", []) if member.get("name")]


def find_member(state: dict[str, Any], role_name: str) -> dict[str, str]:
    for member in state.get("members", []):
        if member.get("name") == role_name:
            return {"name": member.get("name", ""), "persona": member.get("persona", "")}
    return {"name": role_name, "persona": ""}


def valid_next_role(raw_role: Any, names: list[str]) -> str | None:
    role_name = str(raw_role or "").strip()
    if role_name in names:
        return role_name
    return None


def asks_user_for_input(content: str) -> bool:
    text = content.strip()
    if not any(word in text for word in USER_REFERENCE_WORDS):
        return False
    if "?" in text or "？" in text:
        return True
    return any(word in text for word in USER_INPUT_WORDS)


def latest_ai_message_waits_for_user(state: dict[str, Any]) -> bool:
    for message in reversed(state.get("messages", [])):
        if message.type == "human":
            return False
        if message.type == "ai":
            return asks_user_for_input(str(message.content))
    return False


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
    max_rounds = int(state.get("max_rounds") or 5)
    member = find_member(state, role_name)
    names = member_names(state)
    group_intro = str(state.get("group_intro") or "未设置")
    user_persona = str(state.get("user_persona") or "未设置")
    thread_id = get_thread_id(config)

    if latest_ai_message_waits_for_user(state):
        return {"next_role": None, "should_end": True}

    system_prompt = (
        f"你是群聊中的{role_name}。\n"
        f"群聊简介/氛围：{group_intro}。\n"
        f"你的角色人设：{member['persona'] or '按该岗位的专业职责发言'}。\n"
        f"用户在群聊中的身份/人设：{user_persona}。\n"
        f"群聊成员：{', '.join(names)}。\n"
        f"最多自动讨论条数：{max_rounds}，当前已生成 {round_count} 条。\n"
        "请只代表你自己的角色发言，像真实群聊一样自然接话。默认使用轻松、口语、短句的表达，可以有一点闲聊感。\n"
        "需要专业判断时再给具体建议，不要每次都写成会议纪要、评审意见或任务清单。不要替其他角色总结，不要输出角色名前缀。\n"
        "你发言后需要判断群聊是否还应该继续。如果继续，请从群聊成员中选择下一位最适合自然接话的人。\n"
        "可以回应用户，也可以回应上一位群成员；可以补充、反问、轻微分歧或顺着聊。尽量不要指定自己连续发言。\n"
        "如果你的发言是在向用户、群主或业务方索要主题、目标、需求、时间、确认或补充信息，必须结束本轮，等待用户回复。\n"
        "如果最近已经有人向用户要信息，不要换个说法重复追问，也要结束。\n"
        "如果讨论已经自然收束，或者再聊只会重复，就结束。\n"
        "只输出 JSON，不要输出其他文字。格式："
        '{"content":"你的回复内容","should_continue":true,"next_role":"角色名"} '
        '或 {"content":"你的回复内容","should_continue":false,"next_role":""}'
    )
    messages = [{"role": "system", "content": system_prompt}]
    messages.extend(history_for_model(state))

    if not settings.dashscope_api_key:
        content = f"我是{role_name}，当前还没有配置可用的模型调用密钥。"
        should_continue = False
        next_role = None
    else:
        logger.info(
            "Group chat role LLM request: thread_id=%s role_name=%s model=%s messages=%s",
            thread_id,
            role_name,
            settings.dashscope_model,
            messages,
        )
        response_text = await call_llm(thread_id=thread_id, messages=messages)
        response = parse_json_object(response_text)
        content = str(response.get("content") or response_text).strip()
        should_continue = bool(response.get("should_continue"))
        next_role = valid_next_role(response.get("next_role"), names)

    if asks_user_for_input(content):
        should_continue = False
        next_role = None

    next_round_count = round_count + 1
    if next_round_count >= max_rounds or not should_continue or not next_role:
        should_end = True
        next_role = None
    else:
        should_end = False

    return {
        "messages": [AIMessage(content=content, name=role_name)],
        "next_role": next_role,
        "should_end": should_end,
        "round_count": next_round_count,
    }

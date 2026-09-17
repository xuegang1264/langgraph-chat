import logging
from typing import Any

from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig

from app.agent.groupGraph.node.common import (
    ROLE_NODE_BY_NAME,
    call_llm,
    get_thread_id,
    history_for_model,
    member_names,
    parse_json_object,
)
from app.core.config import settings


logger = logging.getLogger(__name__)


def _sanitize_next_role(raw_role: Any, names: list[str]) -> str | None:
    role_name = str(raw_role or "").strip()
    if role_name in names:
        return role_name
    return None


async def router_node(state: dict[str, Any], config: RunnableConfig) -> dict[str, Any]:
    current_message = str(state.get("current_message", "")).strip()
    round_count = int(state.get("round_count") or 0)
    max_rounds = int(state.get("max_rounds") or 5)
    names = member_names(state)

    if not current_message and round_count == 0:
        return {"should_end": True, "next_role": None}

    if not names or round_count >= max_rounds:
        updates: dict[str, Any] = {
            "should_end": True,
            "next_role": None,
        }
        if current_message and round_count == 0:
            updates["messages"] = [HumanMessage(content=current_message)]
        return updates

    if not settings.dashscope_api_key:
        updates = {"should_end": True, "next_role": None}
        if current_message and round_count == 0:
            updates["messages"] = [HumanMessage(content=current_message)]
        return updates

    prompt = (
        "你是一个多人群聊的发言调度节点。你只负责决定用户发起后第一位由谁接话，或者直接结束。\n"
        f"用户本轮发言：{current_message}\n"
        f"群聊简介/氛围：{state.get('group_intro') or '未设置'}\n"
        f"用户身份或主持控制要求：{state.get('user_persona') or '未设置'}\n"
        f"群聊成员：{', '.join(names)}\n"
        f"最多自动讨论条数：{max_rounds}。\n"
        "如果不需要群成员接话，输出 action=end。否则选择最适合自然接第一句的群成员。\n"
        "只输出 JSON，不要输出其他文字。格式："
        '{"action":"continue","next_role":"角色名","reason":"原因"} '
        '或 {"action":"end","reason":"原因"}'
    )
    messages = [
        {"role": "system", "content": "你只负责群聊发言调度，必须输出合法 JSON。"},
        *history_for_model(state),
        {"role": "user", "content": prompt},
    ]
    logger.info(
        "Group chat router LLM request: thread_id=%s model=%s messages=%s",
        get_thread_id(config),
        settings.dashscope_model,
        messages,
    )
    decision_text = await call_llm(thread_id=get_thread_id(config), messages=messages)
    decision = parse_json_object(decision_text)

    next_role = None
    if decision.get("action") == "continue":
        next_role = _sanitize_next_role(decision.get("next_role"), names) or names[0]

    updates = {
        "should_end": not bool(next_role),
        "next_role": next_role,
    }
    if current_message and round_count == 0:
        updates["messages"] = [HumanMessage(content=current_message)]

    return updates


def route_next_role(state: dict[str, Any]) -> str:
    if state.get("should_end"):
        return "end"

    role_name = state.get("next_role")
    return ROLE_NODE_BY_NAME.get(str(role_name), "end")


def route_after_role(state: dict[str, Any]) -> str:
    if state.get("should_end"):
        return "end"

    round_count = int(state.get("round_count") or 0)
    max_rounds = int(state.get("max_rounds") or 5)
    if round_count >= max_rounds:
        return "end"

    role_name = state.get("next_role")
    return ROLE_NODE_BY_NAME.get(str(role_name), "end")

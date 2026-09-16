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


def _fallback_next_role(names: list[str], spoken_roles: list[str]) -> str | None:
    for name in names:
        if name not in spoken_roles:
            return name
    return None


async def router_node(state: dict[str, Any], config: RunnableConfig) -> dict[str, Any]:
    current_message = str(state.get("current_message", "")).strip()
    round_count = int(state.get("round_count") or 0)
    max_rounds = int(state.get("max_rounds") or 5)
    spoken_roles = list(state.get("spoken_roles") or [])
    names = member_names(state)

    if not current_message and round_count == 0:
        return {"should_end": True, "next_role": None}

    if not names or round_count >= max_rounds:
        updates: dict[str, Any] = {"should_end": True, "next_role": None}
        if current_message and round_count == 0:
            updates["messages"] = [HumanMessage(content=current_message)]
        return updates

    if not settings.dashscope_api_key:
        updates = {"should_end": True, "next_role": None}
        if current_message and round_count == 0:
            updates["messages"] = [HumanMessage(content=current_message)]
        return updates

    available_roles = [name for name in names if name not in spoken_roles]
    if not available_roles:
        return {"should_end": True, "next_role": None}

    prompt = (
        "你是一个多人群聊的调度节点。你需要判断下一步由哪个角色发言，或者结束本轮讨论。\n"
        f"用户本轮发言：{current_message}\n"
        f"用户人设：{state.get('user_persona') or '未设置'}\n"
        f"群聊成员：{', '.join(names)}\n"
        f"本轮已经发言的角色：{', '.join(spoken_roles) if spoken_roles else '无'}\n"
        f"剩余可发言角色：{', '.join(available_roles)}\n"
        f"最多发言轮数：{max_rounds}，当前已发言轮数：{round_count}\n"
        "如果问题已经回答充分，输出 action=end。否则从剩余可发言角色中选择最应该发言的一位。\n"
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

    next_role = str(decision.get("next_role") or "").strip()
    should_continue = decision.get("action") == "continue"
    if not should_continue:
        next_role = ""

    if should_continue and next_role not in available_roles:
        next_role = _fallback_next_role(names, spoken_roles) or ""

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

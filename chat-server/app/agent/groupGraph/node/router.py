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


def _fallback_role_sequence(available_roles: list[str], max_count: int) -> list[str]:
    return available_roles[:max_count]


def _sanitize_role_sequence(
    raw_sequence: Any,
    available_roles: list[str],
    max_count: int,
) -> list[str]:
    if isinstance(raw_sequence, str):
        candidates = [raw_sequence]
    elif isinstance(raw_sequence, list):
        candidates = [str(role).strip() for role in raw_sequence]
    else:
        candidates = []

    available = set(available_roles)
    sequence: list[str] = []
    for role in candidates:
        if role in available and role not in sequence:
            sequence.append(role)
        if len(sequence) >= max_count:
            break

    return sequence


def _next_role_from_sequence(state: dict[str, Any]) -> str | None:
    spoken_roles = set(state.get("spoken_roles") or [])
    for role_name in state.get("role_sequence") or []:
        if role_name not in spoken_roles:
            return str(role_name)
    return None


async def router_node(state: dict[str, Any], config: RunnableConfig) -> dict[str, Any]:
    current_message = str(state.get("current_message", "")).strip()
    round_count = int(state.get("round_count") or 0)
    max_rounds = int(state.get("max_rounds") or 5)
    spoken_roles = list(state.get("spoken_roles") or [])
    names = member_names(state)

    if not current_message and round_count == 0:
        return {"should_end": True, "next_role": None, "role_sequence": []}

    if not names or round_count >= max_rounds:
        updates: dict[str, Any] = {
            "should_end": True,
            "next_role": None,
            "role_sequence": [],
        }
        if current_message and round_count == 0:
            updates["messages"] = [HumanMessage(content=current_message)]
        return updates

    if not settings.dashscope_api_key:
        updates = {"should_end": True, "next_role": None, "role_sequence": []}
        if current_message and round_count == 0:
            updates["messages"] = [HumanMessage(content=current_message)]
        return updates

    available_roles = [name for name in names if name not in spoken_roles]
    if not available_roles:
        return {"should_end": True, "next_role": None, "role_sequence": []}

    remaining_rounds = max_rounds - round_count
    max_planned_roles = min(len(available_roles), remaining_rounds)
    replan_reason = str(state.get("replan_reason") or "").strip()
    prompt = (
        "你是一个多人群聊的调度节点。你需要一次性规划接下来需要发言的角色顺序，或者结束本轮讨论。\n"
        f"用户本轮发言：{current_message}\n"
        f"群聊简介/氛围：{state.get('group_intro') or '未设置'}\n"
        f"用户人设：{state.get('user_persona') or '未设置'}\n"
        f"群聊成员：{', '.join(names)}\n"
        f"本轮已经发言的角色：{', '.join(spoken_roles) if spoken_roles else '无'}\n"
        f"剩余可发言角色：{', '.join(available_roles)}\n"
        f"最多发言轮数：{max_rounds}，当前已发言轮数：{round_count}\n"
        f"最多还能规划 {max_planned_roles} 位角色。\n"
        f"重排原因：{replan_reason or '无'}\n"
        "如果问题已经回答充分，输出 action=end。否则输出 role_sequence，表示接下来依次发言的角色。\n"
        "role_sequence 必须只包含剩余可发言角色，不要包含已经发言的角色，不要重复，长度不要超过最多还能规划的人数。\n"
        "优先选择真正能推进当前问题的角色，不需要让所有角色都发言。\n"
        "只输出 JSON，不要输出其他文字。格式："
        '{"action":"continue","role_sequence":["角色名1","角色名2"],"reason":"原因"} '
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

    should_continue = decision.get("action") == "continue"
    role_sequence = []
    if should_continue:
        role_sequence = _sanitize_role_sequence(
            decision.get("role_sequence") or decision.get("next_role"),
            available_roles,
            max_planned_roles,
        )
        if not role_sequence:
            fallback = _fallback_next_role(names, spoken_roles)
            role_sequence = [fallback] if fallback else _fallback_role_sequence(
                available_roles,
                max_planned_roles,
            )

    next_role = role_sequence[0] if role_sequence else None

    updates = {
        "should_end": not bool(role_sequence),
        "next_role": next_role,
        "role_sequence": role_sequence,
        "need_replan": False,
        "replan_reason": "",
    }
    if current_message and round_count == 0:
        updates["messages"] = [HumanMessage(content=current_message)]

    return updates


def route_next_role(state: dict[str, Any]) -> str:
    if state.get("should_end"):
        return "end"

    role_name = state.get("next_role") or _next_role_from_sequence(state)
    return ROLE_NODE_BY_NAME.get(str(role_name), "end")


def route_after_role(state: dict[str, Any]) -> str:
    if state.get("should_end"):
        return "end"

    round_count = int(state.get("round_count") or 0)
    max_rounds = int(state.get("max_rounds") or 5)
    if round_count >= max_rounds:
        return "end"

    spoken_roles = set(state.get("spoken_roles") or [])
    names = member_names(state)
    has_available_role = any(name not in spoken_roles for name in names)
    if state.get("need_replan") and has_available_role:
        return "router"

    role_name = _next_role_from_sequence(state)
    return ROLE_NODE_BY_NAME.get(str(role_name), "end")

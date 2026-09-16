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
    group_intro = str(state.get("group_intro") or "未设置")
    user_persona = str(state.get("user_persona") or "未设置")
    thread_id = get_thread_id(config)
    planned_sequence = list(state.get("role_sequence") or [])

    system_prompt = (
        f"你是群聊中的{role_name}。\n"
        f"群聊简介/氛围：{group_intro}。\n"
        f"你的角色人设：{member['persona'] or '按该岗位的专业职责发言'}。\n"
        f"用户在群聊中的身份/人设：{user_persona}。\n"
        f"本轮计划发言顺序：{', '.join(planned_sequence) if planned_sequence else '未规划'}。\n"
        "请只代表你自己的角色发言，像真实群聊一样自然接话。默认使用轻松、口语、短句的表达，可以有一点闲聊感。\n"
        "需要专业判断时再给具体建议，不要每次都写成会议纪要、评审意见或任务清单。不要替其他角色总结，不要输出角色名前缀。\n"
        "你还需要判断是否必须请求重新编排后续发言顺序。只有满足以下任一条件时，need_replan 才能为 true：\n"
        "1. 当前问题缺少继续推进所必需的关键信息，必须让更合适的未发言角色先介入；\n"
        "2. 你发现原计划后续角色明显不适合继续当前讨论，继续按原顺序会降低回答质量；\n"
        "3. 出现你无法处理、但某个未发言角色必须立即介入的重大风险或专业问题；\n"
        "4. 你的回复改变了问题方向，原发言顺序已经不再匹配当前上下文。\n"
        "普通补充、轻微不确定、希望别人再看看、礼貌性协作，都必须输出 need_replan=false。\n"
        "只输出 JSON，不要输出其他文字。格式："
        '{"content":"你的回复内容","need_replan":false,"replan_reason":""} '
        '或 {"content":"你的回复内容","need_replan":true,"replan_reason":"必须重排的具体原因"}'
    )
    messages = [{"role": "system", "content": system_prompt}]
    messages.extend(history_for_model(state))

    if not settings.dashscope_api_key:
        content = f"我是{role_name}，当前还没有配置可用的模型调用密钥。"
        need_replan = False
        replan_reason = ""
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
        need_replan = bool(response.get("need_replan"))
        replan_reason = str(response.get("replan_reason") or "").strip()
        if need_replan and not replan_reason:
            need_replan = False

    if role_name not in spoken_roles:
        spoken_roles.append(role_name)

    return {
        "messages": [AIMessage(content=content, name=role_name)],
        "spoken_roles": spoken_roles,
        "need_replan": need_replan,
        "replan_reason": replan_reason if need_replan else "",
        "round_count": round_count + 1,
    }

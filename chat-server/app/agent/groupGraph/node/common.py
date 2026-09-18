import json
import logging
import re
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.runnables import RunnableConfig

from app.core.config import settings
from app.agent.tools.registry import run_tool, tool_schemas
from app.services import tokenplan


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

USER_REQUEST_PATTERNS = (
    r"(?:请|麻烦|烦请|需要|劳烦)(?:你|您|用户|群主|老板|业务方).{0,16}"
    r"(?:先)?(?:给|说|确认|明确|补充|提供|回复|定|拍板|决定)",
    r"(?:你|您|用户|群主|老板|业务方).{0,8}"
    r"(?:能否|能不能|可否|是否可以|方便|可以).{0,16}"
    r"(?:给|说|确认|明确|补充|提供|回复|定|拍板|决定)",
    r"(?:你|您|用户|群主|老板|业务方)(?:先|也|这边)?"
    r"(?:给|说|确认|明确|补充|提供|回复|定|拍板|决定)(?:下|一下|个)?",
    r"(?:群主|用户|老板|业务方)先"
    r"(?:给|说|确认|明确|补充|提供|回复|定|拍板|决定)(?:下|一下|个)?",
)
USER_REQUEST_QUESTION_PATTERNS = (
    r"(?:你|您|用户|群主|老板|业务方).{0,16}"
    r"(?:能否|能不能|可否|是否可以|方便|可以|要不要|需不需要|是否需要)",
    r"(?:你这边|您这边|用户|群主|老板|业务方).{0,16}"
    r"(?:是什么|是多少|定了吗|确认了吗|补充吗|提供吗)",
)
USER_REQUEST_TARGETS = (
    "主题",
    "目标",
    "需求",
    "时间",
    "日期",
    "预算",
    "人数",
    "范围",
    "标准",
    "背景",
    "信息",
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


def fallback_next_role(current_role: str, names: list[str]) -> str | None:
    if not names:
        return None

    if current_role not in names:
        return names[0]

    current_index = names.index(current_role)
    for offset in range(1, len(names) + 1):
        role_name = names[(current_index + offset) % len(names)]
        if role_name != current_role:
            return role_name
    return None


def minimum_discussion_rounds(max_rounds: int, member_count: int) -> int:
    if max_rounds <= 2:
        return max_rounds
    return min(max_rounds, max(4, min(member_count, 8)))


def asks_user_for_input(content: str) -> bool:
    text = content.strip()
    has_request_target = any(target in text for target in USER_REQUEST_TARGETS)
    if not has_request_target:
        return False

    if any(re.search(pattern, text) for pattern in USER_REQUEST_PATTERNS):
        return True

    has_question_mark = "?" in text or "？" in text
    if has_question_mark and any(
        re.search(pattern, text) for pattern in USER_REQUEST_QUESTION_PATTERNS
    ):
        return True
    return False


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
    return await tokenplan.chat(
        thread_id=thread_id,
        messages=messages,
        model=model or settings.tokenplan_model,
        api_key=settings.tokenplan_api_key,
        base_url=settings.tokenplan_base_url,
    )


async def call_llm_message(
    thread_id: str,
    messages: list[dict[str, Any]],
    model: str | None = None,
    tools: list[dict[str, Any]] | None = None,
    tool_choice: str | dict[str, Any] | None = "auto",
) -> dict[str, Any]:
    return await tokenplan.chat_completion(
        thread_id=thread_id,
        messages=messages,
        model=model or settings.tokenplan_model,
        api_key=settings.tokenplan_api_key,
        base_url=settings.tokenplan_base_url,
        tools=tools,
        tool_choice=tool_choice,
    )


def normalize_role_response(response: dict[str, Any], response_text: str) -> dict[str, Any]:
    if response.get("action") == "respond":
        return response
    if "content" in response:
        return response
    return {"content": response_text, "should_continue": False, "next_role": ""}


def _tool_call_id(tool_call: dict[str, Any], index: int) -> str:
    return str(tool_call.get("id") or f"tool_call_{index}")


def _tool_call_name_and_args(tool_call: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    function = tool_call.get("function") or {}
    name = str(function.get("name") or tool_call.get("name") or "").strip()
    raw_args = function.get("arguments") or tool_call.get("arguments") or {}
    if isinstance(raw_args, str):
        try:
            parsed_args = json.loads(raw_args)
        except json.JSONDecodeError:
            parsed_args = {}
    elif isinstance(raw_args, dict):
        parsed_args = raw_args
    else:
        parsed_args = {}
    return name, parsed_args


def _tool_cache_key(tool_name: str, tool_args: dict[str, Any]) -> str:
    try:
        args_text = json.dumps(tool_args, ensure_ascii=False, sort_keys=True)
    except TypeError:
        args_text = json.dumps(
            {key: str(value) for key, value in tool_args.items()},
            ensure_ascii=False,
            sort_keys=True,
        )
    return f"{tool_name}:{args_text}"


def cached_tool_results_prompt(tool_results: dict[str, dict[str, Any]]) -> str:
    if not tool_results:
        return ""

    lines = ["本轮对话已获取的工具结果，后续角色应优先直接使用，不要重复调用相同工具和参数："]
    for item in tool_results.values():
        lines.append(
            "- "
            f"{item.get('tool_name', 'unknown')} "
            f"参数={item.get('tool_args', {})} "
            f"结果={item.get('result', '')}"
        )
    return "\n".join(lines) + "\n"


async def run_role_llm_with_tools(
    *,
    thread_id: str,
    messages: list[dict[str, Any]],
    tool_results: dict[str, dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    available_tools = tool_schemas()
    working_messages = [*messages]
    next_tool_results = dict(tool_results)

    for _ in range(3):
        assistant_message = await call_llm_message(
            thread_id=thread_id,
            messages=working_messages,
            tools=available_tools,
            tool_choice="auto",
        )
        tool_calls = assistant_message.get("tool_calls") or []
        if not tool_calls:
            response_text = str(assistant_message.get("content") or "")
            return (
                normalize_role_response(parse_json_object(response_text), response_text),
                next_tool_results,
            )

        working_messages.append(assistant_message)
        for index, tool_call in enumerate(tool_calls):
            tool_call_id = _tool_call_id(tool_call, index)
            tool_name, tool_args = _tool_call_name_and_args(tool_call)
            cache_key = _tool_cache_key(tool_name, tool_args)
            cached_result = next_tool_results.get(cache_key)
            if cached_result:
                tool_result = str(cached_result.get("result") or "")
            else:
                try:
                    tool_result = await run_tool(tool_name, tool_args)
                except Exception as exc:
                    logger.warning(
                        "Role tool call failed: thread_id=%s tool_name=%s",
                        thread_id,
                        tool_name,
                        exc_info=True,
                    )
                    tool_result = f"工具调用失败：{type(exc).__name__}: {exc}"
                next_tool_results[cache_key] = {
                    "tool_name": tool_name,
                    "tool_args": tool_args,
                    "result": tool_result,
                }
            working_messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call_id,
                    "content": tool_result,
                }
            )

    final_message = await call_llm_message(
        thread_id=thread_id,
        messages=working_messages,
        tools=available_tools,
        tool_choice="none",
    )
    response_text = str(final_message.get("content") or "")
    return (
        normalize_role_response(parse_json_object(response_text), response_text),
        next_tool_results,
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
    min_rounds = minimum_discussion_rounds(max_rounds, len(names))
    group_intro = str(state.get("group_intro") or "未设置")
    user_persona = str(state.get("user_persona") or "未设置")
    thread_id = get_thread_id(config)
    tool_results = dict(state.get("tool_results") or {})

    if latest_ai_message_waits_for_user(state):
        return {"next_role": None, "should_end": True}

    system_prompt = (
        f"你是群聊中的{role_name}。\n"
        f"群聊简介/氛围：{group_intro}。\n"
        f"你的角色人设：{member['persona'] or '按该岗位的专业职责发言'}。\n"
        f"用户在群聊中的身份或主持控制要求：{user_persona}。\n"
        f"群聊成员：{', '.join(names)}。\n"
        f"最多自动讨论条数：{max_rounds}，当前已生成 {round_count} 条，通常至少聊到 {min_rounds} 条再自然收束。\n"
        "角色人设可能同时包含工作背景、生活偏好和说话风格。请根据当前话题自然选择侧重点：聊工作时专业，闲聊时像普通群友，不要强行转成项目分析。\n"
        "请只代表你自己的角色发言，像真实群聊一样自然接话。默认使用轻松、口语、短句的表达，可以有一点闲聊感。\n"
        "需要专业判断时再给具体建议，不要每次都写成会议纪要、评审意见或任务清单。不要替其他角色总结，不要输出角色名前缀。\n"
        "你发言后需要判断群聊是否还应该继续。如果继续，请从群聊成员中选择下一位最适合自然接话的人。\n"
        "可以回应用户，也可以回应上一位群成员；可以补充、反问、轻微分歧或顺着聊。尽量不要指定自己连续发言。\n"
        "如果你的发言是在向用户、群主或业务方索要主题、目标、需求、时间、确认或补充信息，必须结束本轮，等待用户回复。\n"
        "如果最近已经有人向用户要信息，不要换个说法重复追问，也要结束。\n"
        "如果还没聊够最低条数，且不是在等待用户回复，就尽量继续点下一位群成员接话，营造多人群聊感。\n"
        "聊够最低条数后，如果讨论已经自然收束，或者再聊只会重复，就结束。\n"
        f"{cached_tool_results_prompt(tool_results)}"
        "如需查询实时信息，可以使用系统提供的工具；不要编造工具能查询到的信息。\n"
        "最终发言必须只输出 JSON，不要输出其他文字。格式："
        '{"action":"respond","content":"你的回复内容","should_continue":true,"next_role":"角色名"} '
        '或 {"action":"respond","content":"你的回复内容","should_continue":false,"next_role":""}。\n'
        "兼容格式也可以直接输出："
        '{"content":"你的回复内容","should_continue":true,"next_role":"角色名"}'
    )
    messages = [{"role": "system", "content": system_prompt}]
    messages.extend(history_for_model(state))

    if not settings.tokenplan_api_key:
        content = f"我是{role_name}，当前还没有配置可用的模型调用密钥。"
        should_continue = False
        next_role = None
    else:
        logger.info(
            "Group chat role LLM request: thread_id=%s role_name=%s model=%s messages=%s",
            thread_id,
            role_name,
            settings.tokenplan_model,
            messages,
        )
        response, tool_results = await run_role_llm_with_tools(
            thread_id=thread_id,
            messages=messages,
            tool_results=tool_results,
        )
        content = str(response.get("content") or "").strip()
        should_continue = bool(response.get("should_continue"))
        next_role = valid_next_role(response.get("next_role"), names)

    if asks_user_for_input(content):
        should_continue = False
        next_role = None

    next_round_count = round_count + 1
    if next_round_count >= max_rounds:
        should_end = True
        next_role = None
    elif next_round_count < min_rounds:
        next_role = next_role or fallback_next_role(role_name, names)
        should_end = not bool(next_role)
    elif not should_continue or not next_role:
        should_end = True
        next_role = None
    else:
        should_end = False

    return {
        "messages": [AIMessage(content=content, name=role_name)],
        "next_role": next_role,
        "should_end": should_end,
        "round_count": next_round_count,
        "tool_results": tool_results,
    }

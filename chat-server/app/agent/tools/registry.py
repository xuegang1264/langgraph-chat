from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from app.agent.tools.weather import query_qweather


ToolFunc = Callable[..., Awaitable[str]]


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]
    func: ToolFunc

    def schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


QUERY_QWEATHER = ToolSpec(
    name="query_qweather",
    description=(
        "查询天气的统一入口。当前/今天实时天气用 intent=current；"
        "未来几天、明天、周末、一周天气用 intent=daily；"
        "接下来几小时、今天下午、今晚、几点下雨用 intent=hourly。"
        "同一个用户问题通常只调用一次本工具，不要分别调用多个天气工具。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "location": {
                "type": "string",
                "description": "城市名或地点名，例如：南京、北京、上海",
            },
            "intent": {
                "type": "string",
                "enum": ["current", "daily", "hourly"],
                "description": "查询类型：current=当前天气，daily=未来几天，hourly=未来几小时",
            },
            "days": {
                "type": "integer",
                "description": "daily 查询的天数，1 到 10，默认 7",
                "minimum": 1,
                "maximum": 10,
            },
            "hours": {
                "type": "integer",
                "description": "hourly 查询的小时数，1 到 240，默认 24",
                "minimum": 1,
                "maximum": 240,
            },
        },
        "required": ["location", "intent"],
    },
    func=query_qweather,
)


TOOLS = (QUERY_QWEATHER,)
TOOL_BY_NAME = {tool.name: tool for tool in TOOLS}


def tool_schemas() -> list[dict[str, Any]]:
    return [tool.schema() for tool in TOOLS]


async def run_tool(tool_name: str, tool_args: dict[str, Any]) -> str:
    tool = TOOL_BY_NAME.get(tool_name)
    if not tool:
        raise ValueError(f"未知工具：{tool_name}")
    return await tool.func(**tool_args)

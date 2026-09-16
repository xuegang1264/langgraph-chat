from typing import Any

from langchain_core.runnables import RunnableConfig

from app.agent.groupGraph.node.common import run_role_node


async def pmo_node(state: dict[str, Any], config: RunnableConfig) -> dict[str, Any]:
    return await run_role_node(state, config, "PMO")

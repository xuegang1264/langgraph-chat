from typing import Annotated, TypedDict

try:
    from typing import NotRequired
except ImportError:
    from typing_extensions import NotRequired

from langchain_core.messages import AnyMessage
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages

from app.agent.groupGraph.node.architect import architect_node
from app.agent.groupGraph.node.backend_dev import backend_dev_node
from app.agent.groupGraph.node.business_owner import business_owner_node
from app.agent.groupGraph.node.frontend_dev import frontend_dev_node
from app.agent.groupGraph.node.pmo import pmo_node
from app.agent.groupGraph.node.product_manager import product_manager_node
from app.agent.groupGraph.node.project_manager import project_manager_node
from app.agent.groupGraph.node.router import route_after_role, route_next_role, router_node
from app.agent.groupGraph.node.tester import tester_node


class GroupMember(TypedDict):
    name: str
    persona: str


class GroupChatState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]
    current_message: NotRequired[str]
    group_intro: NotRequired[str]
    user_persona: NotRequired[str]
    members: NotRequired[list[GroupMember]]
    next_role: NotRequired[str | None]
    should_end: NotRequired[bool]
    round_count: NotRequired[int]
    max_rounds: NotRequired[int]


def build_group_chat_graph(checkpointer: BaseCheckpointSaver | None = None):
    graph = StateGraph(GroupChatState)
    graph.add_node("router", router_node)
    graph.add_node("product_manager", product_manager_node)
    graph.add_node("project_manager", project_manager_node)
    graph.add_node("pmo", pmo_node)
    graph.add_node("backend_dev", backend_dev_node)
    graph.add_node("frontend_dev", frontend_dev_node)
    graph.add_node("tester", tester_node)
    graph.add_node("architect", architect_node)
    graph.add_node("business_owner", business_owner_node)

    graph.add_edge(START, "router")
    graph.add_conditional_edges(
        "router",
        route_next_role,
        {
            "product_manager": "product_manager",
            "project_manager": "project_manager",
            "pmo": "pmo",
            "backend_dev": "backend_dev",
            "frontend_dev": "frontend_dev",
            "tester": "tester",
            "architect": "architect",
            "business_owner": "business_owner",
            "end": END,
        },
    )
    role_route_map = {
        "product_manager": "product_manager",
        "project_manager": "project_manager",
        "pmo": "pmo",
        "backend_dev": "backend_dev",
        "frontend_dev": "frontend_dev",
        "tester": "tester",
        "architect": "architect",
        "business_owner": "business_owner",
        "end": END,
    }
    for node_name in (
        "product_manager",
        "project_manager",
        "pmo",
        "backend_dev",
        "frontend_dev",
        "tester",
        "architect",
        "business_owner",
    ):
        graph.add_conditional_edges(node_name, route_after_role, role_route_map)

    return graph.compile(checkpointer=checkpointer)

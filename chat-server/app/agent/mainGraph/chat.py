from typing import Annotated, TypedDict

try:
    from typing import NotRequired
except ImportError:
    from typing_extensions import NotRequired

from langchain_core.messages import AnyMessage
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages

from app.agent.mainGraph.node.main_chat import main_chat_node


class ChatState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]
    current_message: NotRequired[str]


def build_chat_graph(checkpointer: BaseCheckpointSaver | None = None):
    graph = StateGraph(ChatState)
    graph.add_node("chat", main_chat_node)
    graph.add_edge(START, "chat")
    graph.add_edge("chat", END)
    return graph.compile(checkpointer=checkpointer)

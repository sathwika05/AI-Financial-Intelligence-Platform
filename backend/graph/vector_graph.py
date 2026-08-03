





import operator
from typing import Annotated, TypedDict
import logging

from langgraph.graph import END, START, StateGraph

from backend.nodes.vector_node import vector_node, vector_tool_node


logger = logging.getLogger(__name__)

class VectorState(TypedDict):
    messages: Annotated[list, operator.add]

def should_continue(state: VectorState):
    last = state["messages"][-1]
    if hasattr(last, "tool_calls") and last.tool_calls:
        return "tools"
    return END

def build_vector_graph():
    graph = StateGraph(VectorState)
    graph.add_node("agent",vector_node)
    graph.add_node("tools",vector_tool_node)

    graph.add_edge(START, "agent")
    graph.add_conditional_edges(
        "agent", should_continue, ["tools",END]
    )
    graph.add_edge("tools","agent")
    logger.info("[VECTOR_GRAPH] Graph compiled")
    return graph.compile()

vector_graph = build_vector_graph()
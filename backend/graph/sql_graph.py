from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode

from backend.nodes.sql_node import SQLAgentState, capture_sql_tool_outputs, sql_agent_node, should_continue_sql
from backend.retrieval.sql_executor import sql_tools


sql_builder = StateGraph(SQLAgentState)

# nodes
sql_builder.add_node("sql_agent", sql_agent_node)
sql_builder.add_node("tools", ToolNode(sql_tools))
sql_builder.add_node("capture_tool_outputs",capture_sql_tool_outputs)

# entry point
sql_builder.add_edge(START,"sql_agent")

# edges
sql_builder.add_conditional_edges(
    "sql_agent",
    should_continue_sql,
    {
        "tools",
        END,
    },
)

sql_builder.add_edge(
    "tools",
    "capture_tool_outputs",
)

sql_builder.add_edge("capture_tool_outputs", "sql_agent")

# compiled sql graph
sql_graph = sql_builder.compile()
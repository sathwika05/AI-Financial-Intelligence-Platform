from typing import Annotated, TypedDict

from langchain_core.messages import SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import END, add_messages

from backend.retrieval.sql_executor import SCHEMA, sql_tools

llm = ChatOpenAI(model="gpt-5.4-mini", temperature=0)
llm_with_tools = llm.bind_tools(sql_tools)


class SQLAgentState(TypedDict):
    messages: Annotated[list, add_messages]
    retry_count: int
    original_question: str
    last_sql: str


def sql_agent_node(state: SQLAgentState):
    retry_count = state.get("retry_count", 0)

    last_message = state["messages"][-1]

    if getattr(last_message, "type", None) == "tool" and getattr(last_message, "name", None) == "fix_sql_error":
        retry_count += 1

    system_prompt = f"""
    You are an expert SQL analyst for a financial intelligence database.

    Database Schema:
    {SCHEMA}

    Workflow:
    1. Use get_database_schema if needed
    2. Use generate_sql_query to create SQL
    3. Use execute_sql_query to run the validated query
    4. If execution fails, use fix_sql_error and retry up to 3 times

    Rules:
    - Only SELECT queries are allowed
    - Use only available tables and columns
    - Provide a clear final answer based on query results
    - If you fail after 3 attempts, explain what went wrong
"""

    messages = [SystemMessage(content=system_prompt)] + state["messages"]
    response = llm_with_tools.invoke(messages)

    return {
        "messages": [response],
        "retry_count": retry_count,
        "original_question": state["messages"][0].content,
        "last_sql": state.get("last_sql", ""),
    }


def should_continue_sql(state: SQLAgentState):
    last_message = state["messages"][-1]

    if hasattr(last_message, "tool_calls") and last_message.tool_calls:
        for tool_call in last_message.tool_calls:
            if tool_call["name"] == "fix_sql_error" and state.get("retry_count", 0) >= 3:
                return END

        return "tools"

    return END
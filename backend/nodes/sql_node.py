
import json
import operator
from typing import Annotated, Any, TypedDict

from langchain_core.messages import BaseMessage, SystemMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, add_messages

from backend.llm.llm_context import get_llm_client
from backend.llm.llm_tiers import LLMTier
from backend.retrieval.sql_executor import SCHEMA, sql_tools


MAX_SQL_RETRIES = 3


class SQLAgentState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]
    retry_count: int
    original_question: str
    last_sql: str
    db_result: dict[str, Any]

    sql_executed_tools: Annotated[
        list[str],
        operator.add,
    ]




async def sql_agent_node(
    state: SQLAgentState,
    config: RunnableConfig,
) -> dict:
    """Generate SQL tool calls or a final response."""

    messages = state.get("messages", [])

    if not messages:
        raise ValueError(
            "SQL agent requires at least one message."
        )

    retry_count = state.get("retry_count", 0)
    last_message = messages[-1]

    if (
        getattr(last_message, "type", None) == "tool"
        and getattr(last_message, "name", None)
        == "fix_sql_error"
    ):
        retry_count += 1

    llm = get_llm_client(
        config,
        LLMTier.MEDIUM,
    )

    llm_with_tools = llm.bind_tools(sql_tools)

    system_prompt = f"""
You are an expert SQL analyst for a financial intelligence database.

Database schema:
{SCHEMA}

Workflow:
1. Use get_database_schema when schema clarification is needed.
2. Use generate_sql_query to create a SQL query.
3. Use execute_sql_query to execute the validated query.
4. If execution fails, use fix_sql_error.
5. Retry failed SQL queries no more than {MAX_SQL_RETRIES} times.

Rules:
- Only SELECT queries are allowed.
- Use only tables and columns available in the schema.
- Never modify or delete database data.
- Base the final answer only on returned query results.
- Provide a clear and concise final answer.
- After {MAX_SQL_RETRIES} failed attempts, explain why the query could not be completed.
""".strip()

    invocation_messages = [
        SystemMessage(content=system_prompt),
        *messages,
    ]

    response = await llm_with_tools.ainvoke(
        invocation_messages,
        config=config,
    )

    original_question = state.get(
        "original_question"
    )

    if not original_question:
        first_message_content = messages[0].content

        original_question = (
            first_message_content
            if isinstance(first_message_content, str)
            else str(first_message_content)
        )

    return {
        "messages": [response],
        "retry_count": retry_count,
        "original_question": original_question,
    }


def should_continue_sql(
    state: SQLAgentState,
) -> str:
    """Route tool calls to the tool node or finish the graph."""

    messages = state.get("messages", [])

    if not messages:
        return END

    last_message = messages[-1]

    tool_calls = getattr(
        last_message,
        "tool_calls",
        None,
    )

    if not tool_calls:
        return END

    retry_count = state.get("retry_count", 0)

    for tool_call in tool_calls:
        tool_name = tool_call.get("name")

        if (
            tool_name == "fix_sql_error"
            and retry_count >= MAX_SQL_RETRIES
        ):
            return END

    return "tools"

def capture_sql_tool_outputs(state: SQLAgentState,)-> dict[str, Any]:
    messages = state.get("messages",[])

    latest_tool_messages: list[ToolMessage] = []

    for message in reversed(messages):
        if not isinstance(message, ToolMessage):
            break

        latest_tool_messages.append(message)

    latest_tool_messages.reverse()

    if not latest_tool_messages:
        return {}

    updates: dict[str, Any]={
        "sql_executed_tools": [],
    }

    for message in latest_tool_messages:
        tool_name = message.name
        content = _parse_tool_content(
            message.content
        )

        if tool_name:
            updates["sql_executed_tools"].append(tool_name)

        if tool_name in {"generate_sql_query","fix_sql_error"}:
            sql = _extract_sql(content)

            if sql:
                updates["last_sql"]=sql

        elif tool_name == "execute_sql_query":
            updates["db_result"]=(
                _normalize_db_result(content)
            )
    return updates

def _parse_tool_content(content: Any) -> Any:
    if not isinstance(content, str):
        return content

    content = content.strip()

    if not content:
        return ""

    try:
        return json.loads(content)
    except json.JSONDecodeError:
        return content

def _extract_sql(content: Any)-> str:
    if isinstance(content, dict):
        sql = (
            content.get("sql")
            or content.get("sql_query")
            or content.get("generated_sql")
            or content.get("query")
        )
        return str(sql).strip() if sql else ""

    if isinstance(content,str):
        return content.strip()

    return ""

def _normalize_db_result(content: Any,) -> dict[str, Any]:
    if isinstance(content, dict):
        return content

    if isinstance(content, list):
        return {
            "data": content,
            "error": None,
        }
    return {
        "data": content,
        "error": None,
    }






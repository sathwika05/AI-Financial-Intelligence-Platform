import re

from langchain_community.utilities import SQLDatabase
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
import logging

from backend.config import settings
from backend.llm.llm_context import get_llm_client
from backend.llm.llm_tiers import LLMTier


ALLOWED_TABLES = ["companies", "financial_metrics", "documents"]

logger = logging.getLogger(__name__)

db = SQLDatabase.from_uri(
    settings.SYNC_DATABASE_URL,
    include_tables=ALLOWED_TABLES,
    sample_rows_in_table_info=2,
)

SCHEMA = db.get_table_info()


@tool
def get_database_schema(table_name: str = None)-> str:
    """Get database schema information for SQL query generation."""

    if table_name:
        tables = db.get_usable_table_names()

        if table_name.lower() in [t.lower() for t in tables]:
            return db.get_table_info([table_name])

        return f"Error: '{table_name}' not found. Available tables: {', '.join(tables)}"

    return SCHEMA


@tool
def generate_sql_query(question: str, config: RunnableConfig, schema_info: str = None):
    """Generate a safe PostgreSQL SELECT query from a user question."""

    llm = get_llm_client(
        config,
        LLMTier.MEDIUM,
    )

    schema_to_use = schema_info if schema_info else SCHEMA

    prompt = f"""
    Based on this database schema:

    {schema_to_use}

    Generate a SQL query to answer this question:
    {question}

    Rules:
    - Use only SELECT statements
    - Use only existing tables and columns
    - Add WHERE, GROUP BY, ORDER BY clauses when needed
    - Limit results to 10 rows unless specified otherwise
    - If using ANY aggregate function (STRING_AGG, COUNT, SUM, AVG, MAX, MIN),
      you MUST add GROUP BY for every non-aggregated column in SELECT
    - Use PostgreSQL syntax
    - Prefer simple queries without STRING_AGG unless document snippets are explicitly needed
    - When using PostgreSQL functions, use explicit casts when column types may be integer, numeric, or double precision.
    - Return only the SQL query, nothing else
    """

    response = llm.invoke(prompt, config=config,)
    sql_query = response.content.strip()

    logger.info(
    f"[SQL_EXECUTOR] Generated SQL: {sql_query[:80]}..."
    )
    return sql_query


@tool
def validate_sql_query(query: str):
    """Validate SQL query for safety before execution."""

    clean_query = query.strip()
    clean_query = re.sub(r"```sql\s*", "", clean_query, flags=re.IGNORECASE)
    clean_query = re.sub(r"```\s*", "", clean_query, flags=re.IGNORECASE)
    clean_query = clean_query.strip().rstrip(";")

    if not clean_query.lower().startswith("select"):
        return "Error: only SELECT statements are allowed"

    dangerous_keywords = [
        "INSERT",
        "UPDATE",
        "DELETE",
        "ALTER",
        "DROP",
        "CREATE",
        "TRUNCATE",
    ]

    for keyword in dangerous_keywords:
        pattern = r"\b" + keyword + r"\b"
        if re.search(pattern, clean_query, re.IGNORECASE):
            return f"Error: {keyword} operations are not allowed"

    return clean_query


@tool
def execute_sql_query(sql_query: str, question: str = ""):
    """Execute a validated SQL query. Auto-fix once if SQL execution fails."""

    query = validate_sql_query.invoke(sql_query)

    if query.startswith("Error:"):
        return f"Query validation failed: {query}"

    try:
        result = db.run(query)

        if result:
            return f"Query Results: {result}"

        return "Query executed successfully but no result was found."

    except Exception as e:
        logger.error(f"[SQL_EXECUTOR] SQL execution failed: {e}")

        fixed_query = fix_sql_error.invoke({
            "original_query": query,
            "error_message": str(e),
            "question": question
        })

        fixed_query = validate_sql_query.invoke(fixed_query)

        if fixed_query.startswith("Error:"):
            return f"Fixed query validation failed: {fixed_query}"

        try:
            result = db.run(fixed_query)

            if result:
                return f"Query Results: {result}"

            return "Fixed query executed successfully but no result was found."

        except Exception as final_error:
            logger.error(f"[SQL_EXECUTOR] Fixed SQL also failed: {final_error}")

            return (
                "SQL execution failed after auto-fix. "
                f"Original error: {str(e)}. "
                f"Final error: {str(final_error)}."
            )

@tool
async def fix_sql_error(original_query: str, error_message: str, question: str, config: RunnableConfig | None = None,)-> str:
    """Fix a failed SQL query."""

    llm = get_llm_client(
        config,
        LLMTier.MEDIUM,
    )


    system_message = SystemMessage(
        content="""
        You repair failed PostgreSQL queries.

        Rules:
            - Return only corrected SQL.
            - Use only SELECT or read-only WITH queries.
            - Use only tables and columns present in the supplied schema.
            - Preserve the original user intent.
            - Fix PostgreSQL casts and function signatures.
            - Qualify ambiguous columns with table aliases.
            - Add every non-aggregated selected column to GROUP BY.
            - Never introduce unknown tables or columns.
            - Never use data-changing statements.
            """.strip()
        )

    human_message = HumanMessage(
                content=f"""
                    ORIGINAL QUESTION:
                            {question}

                    FAILED SQL:
                            {original_query}

                    DATABASE ERROR:
                            {error_message}

                    DATABASE SCHEMA:
                            {SCHEMA}

                    Return only corrected SQL.
                    """.strip()
        )

    response = await llm.ainvoke(
        [
            system_message,
            human_message,
        ],
        config=config,
    )
    fixed_query = response.content.strip()

    logger.info(
    f"[SQL_EXECUTOR] Generated SQL: {fixed_query[:80]}..."
    )
    return fixed_query


sql_tools = [
    get_database_schema,
    generate_sql_query,
    execute_sql_query,
    fix_sql_error,
]
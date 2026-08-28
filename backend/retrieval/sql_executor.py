import json
import re
from functools import lru_cache
from typing import Any

from langchain_community.utilities import SQLDatabase
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
import logging
from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import create_async_engine

from backend.config import settings
from backend.llm.llm_context import get_llm_client
from backend.llm.llm_tiers import LLMTier
from backend.config import settings
from backend.services.postgres_service import engine as async_engine

# Generated SQL runs here, so it runs with the narrowest privileges
# available. validate_sql_query enumerates forbidden keywords, which cannot
# cover COPY, GRANT, pg_sleep, pg_read_file or pg_catalog reads; a
# SELECT-only role covers all of them at once, and cannot be argued with the
# way a prompt can.
#
# Falls back to the application engine when the role is not configured, so a
# checkout without it still runs. scripts/create_readonly_role.sql creates
# the role.
read_engine = (
    create_async_engine(settings.READONLY_DATABASE_URL)
    if settings.READONLY_DATABASE_URL
    else async_engine
)


ALLOWED_TABLES = ["companies", "financial_metrics", "documents"]

logger = logging.getLogger(__name__)

db = SQLDatabase.from_uri(
    settings.SYNC_DATABASE_URL,
    include_tables=ALLOWED_TABLES,
    sample_rows_in_table_info=2,
)

SCHEMA = db.get_table_info()

# SQLDatabase.run() renders rows as a Python repr string, which collapses
# a whole result set into one opaque blob. Downstream scoring needs real
# rows — one evidence candidate per company, with usable column names —
# so SELECTs are executed here and returned as structured JSON. That
# happens on the application's async engine; see _run_select.
#
# This sync engine remains for get_sector_vocabulary alone, which is read
# from inside generate_sql_query — a synchronous tool that cannot await.
#
# SYNC_DATABASE_URL is required regardless: langchain's SQLDatabase above
# builds its own engine internally, rejects an async driver, and offers
# get_table_info() only as a blocking call.
_engine = create_engine(
    settings.SYNC_DATABASE_URL,
    pool_pre_ping=True,
)


async def _run_select(query: str) -> dict[str, Any]:
    """
    Execute a validated SELECT and return structured rows.

    Uses the application's async engine rather than a second sync one. The
    only reason a sync engine existed here was that this function, and the
    tool calling it, were sync — and being sync is what made the auto-fix
    path unreachable, since fix_sql_error is a coroutine that cannot be
    awaited from a sync caller.
    """
    async with read_engine.connect() as conn:
        result = await conn.execute(text(query))

        columns = list(result.keys())
        rows = [
            dict(row._mapping)
            for row in result.fetchall()
        ]

    return {
        "columns": columns,
        "rows": rows,
        "row_count": len(rows),
        "error": None,
        # The query this result actually came from.
        #
        # When the auto-fix path below repairs a failed query, the rows
        # returned are the repaired query's rows while state still held the
        # original. The SQL evaluator then graded two different queries at
        # once: sql_accuracy scored the repaired execution and passed, while
        # sql_equivalence scored the broken original against the golden and
        # the LLM judge approved a query that does not parse. valuation_002
        # scored 1.0 on both while its recorded SQL referenced c.eps, a
        # column companies does not have.
        "executed_sql": query,
    }


@lru_cache(maxsize=1)
def get_sector_vocabulary() -> str:
    """
    The exact values `companies.sector` can hold, as prompt text.

    SCHEMA is built with sample_rows_in_table_info=2, so the generator sees
    two example rows and never learns the sector vocabulary. Left to guess,
    it invents categories the question implies — a request for AI stocks
    produced `WHERE c.sector ILIKE '%AI%'`, which is syntactically valid,
    semantically empty, and returned zero rows.

    There are only eight sectors, so the fix is to state them rather than
    instruct the model to be careful. Cached: the vocabulary changes only
    when companies are reseeded, and this is read on every generation.
    """
    try:
        with _engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT DISTINCT sector FROM companies "
                    "WHERE sector IS NOT NULL ORDER BY sector"
                )
            )
            sectors = [row[0] for row in rows]

    except Exception as e:
        # Never block SQL generation on this. Without it the model is only
        # as uninformed as it was before.
        logger.warning(
            "[SQL_EXECUTOR] Could not read sector vocabulary: %s",
            e,
        )
        return ""

    if not sectors:
        return ""

    return (
        "ALLOWED VALUES:\n"
        "companies.sector holds exactly these "
        f"{len(sectors)} values, and nothing else:\n"
        + "\n".join(f"  - {sector}" for sector in sectors)
        + (
            "\n\nThere is no industry column, no theme column, and no other\n"
            "classification anywhere in this database. `sector` above is the\n"
            "ONLY categorical fact about a company.\n"
            "\n"
            "A category that is not in that list — \"AI\", \"semiconductor\",\n"
            "\"biotech\", \"cloud\", \"fintech\" — is NOT DERIVABLE. You cannot\n"
            "compute it from any column, and you must not try.\n"
            "\n"
            "In particular, NEVER decide category membership by matching text.\n"
            "All of these are forbidden:\n"
            "  WHERE c.sector ILIKE '%AI%'\n"
            "  WHERE c.name ILIKE '%AI%'\n"
            "  WHERE EXISTS (SELECT 1 FROM documents d\n"
            "                WHERE d.company_id = c.id\n"
            "                  AND d.content ILIKE '%AI%')\n"
            "\n"
            "A news article mentioning a topic does not make the company it is\n"
            "filed under a member of that category, and a LIKE pattern matches\n"
            "letters, not meaning: '%AI%' matches \"maintains\", \"details\" and\n"
            "\"aiming\", so an oil producer qualifies as an AI company because\n"
            "one of its articles used the word \"maintains\". This is not a\n"
            "hypothetical — it selected 35 of 50 companies.\n"
            "\n"
            "When the question names a category that is not a sector above:\n"
            "  - if the question names specific companies, filter on those\n"
            "    tickers with c.ticker IN (...)\n"
            "  - otherwise omit the category filter entirely and return the\n"
            "    metrics that were asked for\n"
            "An unfiltered answer over real companies is far better than a\n"
            "filter that silently admits the wrong ones."
        )
    )


def _as_tool_payload(payload: dict[str, Any]) -> str:
    """
    Serialize the tool result.

    sql_node json-decodes tool content, so returning JSON keeps the rows
    structured all the way into state instead of stringifying them.
    """
    return json.dumps(payload, default=str)


def _error_payload(message: str, executed_sql: str = "") -> str:
    return _as_tool_payload(
        {
            "columns": [],
            "rows": [],
            "row_count": 0,
            "error": message,
            "executed_sql": executed_sql,
        }
    )


@tool
def get_database_schema(table_name: str = None)-> str:
    """Get database schema information for SQL query generation."""

    if table_name:
        tables = db.get_usable_table_names()

        if table_name.lower() in [t.lower() for t in tables]:
            return db.get_table_info([table_name])

        return f"Error: '{table_name}' not found. Available tables: {', '.join(tables)}"

    return SCHEMA


def build_generation_prompt(
    question: str,
    schema_info: str = None,
) -> str:
    """The generator's prompt, built without calling anything.

    Separated from generate_sql_query so the rules can be asserted in a
    test. A rule that lives only inside a network call is a rule that
    gets deleted by accident.
    """
    schema_to_use = schema_info if schema_info else SCHEMA

    return f"""
You are an expert PostgreSQL query generator.

DATABASE SCHEMA:
{schema_to_use}

{get_sector_vocabulary()}

USER QUESTION:
{question}

Generate exactly one PostgreSQL SELECT query that answers the question.

CRITICAL RULES:

1. ROW COUNT
- If the user specifies the number of requested results, LIMIT must exactly
  match that number.
- "five companies" -> LIMIT 5
- "top 3 companies" -> LIMIT 3
- "10 largest companies" -> LIMIT 10
- Never replace a user-specified count with another default.
- Use LIMIT 10 only when the user specifies no result count.

- OTHER NUMBERS IN THE QUESTION ARE NOT THE COUNT. A question often
  contains figures that belong to filters — percentages, thresholds,
  prices, years — and none of them set the LIMIT. Read the count as the
  number attached to the thing being returned ("five companies", "top 3
  stocks"), not the nearest number in the sentence.
  Example, and a real failure:
    "Which five companies combine revenue growth above 10% with a P/E
     ratio below 30?"
    -> LIMIT 5. The 10 belongs to `revenue_growth > 0.10` and the 30 to
       `pe_ratio < 30`. Answering this with LIMIT 10 returns ten companies
       for a question that asked for five.
- The count can appear anywhere in the sentence, including before a long
  list of conditions. A count stated early still governs the LIMIT.

2. ORDERING
- "lowest", "smallest", "cheapest" -> ORDER BY ... ASC
- "highest", "largest", "biggest" -> ORDER BY ... DESC
- Order by exactly the metric named in the question.
- Example:
  "smallest market cap" -> ORDER BY market_cap ASC

3. RANKING FIELD VALIDITY
- This rule applies ONLY when the metric decides which companies qualify —
  "the five lowest P/E", "the ten largest by market cap". There a company
  without a P/E is not a low-P/E company, so exclude NULL values for the
  ranking field, and exclude zero or negative values where they would make
  the ranking meaningless.

Examples:
- smallest market cap:
    market_cap IS NOT NULL
    AND market_cap > 0

- lowest P/E ratio:
    pe_ratio IS NOT NULL
    AND pe_ratio > 0

- Do NOT apply it when the question already fixes its cohort: a list of
  companies, a sector, or a theme. There the metric describes the members,
  it does not choose them, and dropping one is a wrong answer.
- Return every company in the cohort, including any whose metric is NULL,
  zero or negative. A NULL P/E is a fact about that company — Intel has
  none because its EPS is negative — and the question asked about it.
- "Rank AMD, INTC and NVDA on valuation and growth" must return three
  rows. Two rows is not a partial answer, it is the wrong cohort.
- For a cohort ranking, select exactly:
      c.ticker, c.name, fm.pe_ratio, fm.eps, fm.revenue_growth
  Those three measures are what the downstream ranker scores on, so all
  three belong in the result whether or not the question names each one.
- Do not add c.market_cap to a cohort ranking. It is not one of the
  measures being ranked, and adding it changes the query being judged.

4. CONDITIONS ON FINANCIAL MEASURES
- Interpret what the question MEANS, not the exact words it uses. Ways of
  describing a company are open-ended; the measures available are not.
  Map whatever the question expresses onto the measure it refers to:

    profitability, earnings, making money   -> eps
    growth, expansion, revenue increase     -> revenue_growth
    valuation, how cheap or expensive       -> pe_ratio
    size, how large a company is            -> market_cap

- A condition saying a measure is positive becomes `> 0`. "Profitable",
  "positive earnings", "earning a profit" and "earnings above zero" all
  mean the same thing: eps > 0.
- These phrasings are EXAMPLES, not a lookup table. A qualifier does not
  stop being a qualifier because its exact wording is missing here. If the
  question narrows which companies it wants, that restriction MUST appear
  in the WHERE clause.
- Dropping a qualifier changes the answer. "Which five profitable
  technology companies have the smallest market caps" is not the same
  question as "which five technology companies have the smallest market
  caps", and returning the second is a wrong answer, not a loose one.

- WHERE THESE MEASURES LIVE. The four measures are split across two
  tables, and the split is not guessable — check it before writing a
  column reference:

      companies          c.market_cap, c.sector, c.ticker, c.name
      financial_metrics  fm.eps, fm.pe_ratio, fm.revenue_growth

  A query using eps, pe_ratio or revenue_growth — in SELECT, WHERE or
  ORDER BY — needs the join:

      JOIN financial_metrics fm ON fm.company_id = c.id

  Neither direction is forgiving. c.eps, c.pe_ratio and c.revenue_growth
  do not exist, and neither does fm.market_cap; PostgreSQL rejects any of
  them before returning a row. A question needing market cap AND a
  financial measure needs both tables: c.market_cap with fm.pe_ratio, not
  both from one. Consult the schema above for the authoritative column
  list of each table.

- The two failures this rule exists to prevent, both observed: writing
  `WHERE c.eps > 0` against companies, which does not execute; and dropping
  the profitability filter altogether because eps was not found on
  companies, which executes and silently answers a different question. The
  second is worse. If a measure the question needs is on another table,
  join to it — never drop the condition to make the query run.

5. REQUIRED IDENTIFIER COLUMNS
- Whenever the query returns companies, the SELECT list MUST include
  c.ticker and c.name, even when the user did not ask for them.
- ticker is not output for the reader — it is the key later stages use to
  match a row to a company. A result without it cannot be matched at all,
  so the row is silently discarded no matter how correct it is.
- This rule outranks rule 6. "Only necessary columns" never removes ticker.

6. SELECT ONLY NECESSARY COLUMNS
- Beyond the identifier columns required by rule 5, select only the columns
  needed to answer the user's question.
- Do not SELECT every column from the tables.
- Do not include unrelated metrics unless needed.

7. NEVER INFER A CATEGORY FROM TEXT
- See ALLOWED VALUES above for the only categorical column that exists.
- Do not decide whether a company belongs to a category by pattern-matching
  any free-text column — not c.name, not c.sector, and above all not
  documents.content.
- A company's news mentioning a topic does not place the company in that
  category, and LIKE matches letters rather than meaning.
- If the question's category is not a listed sector, filter on named tickers
  or do not filter by category at all.

8. SQL SAFETY
- SELECT statements only.
- Use only tables and columns available in the schema.
- Never use INSERT, UPDATE, DELETE, DROP, ALTER, TRUNCATE, or CREATE.

9. AGGREGATION
- If using COUNT, SUM, AVG, MIN, MAX, STRING_AGG, or another aggregate,
  every non-aggregated selected column must appear in GROUP BY.

10. QUERY SIMPLICITY
- Prefer simple joins and filters.
- Do not use STRING_AGG unless document snippets are explicitly required.
- Use PostgreSQL syntax.
- Use explicit casts where PostgreSQL type ambiguity may occur.

Before returning the query, verify:
- requested LIMIT is correct
- ranking column is correct
- ASC/DESC direction is correct
- required NULL/positive filters are present
- c.ticker is in the SELECT list whenever companies are returned
- no category is inferred by matching text in any column
- selected columns are necessary
- query is SELECT-only

Return only the SQL query.
Do not return markdown.
Do not explain the query.
""".strip()


@tool
def generate_sql_query(
    question: str,
    config: RunnableConfig,
    schema_info: str = None,
):
    """Generate a safe PostgreSQL SELECT query from a user question."""

    llm = get_llm_client(
        config,
        LLMTier.MEDIUM,
    )

    logger.info(
        f"[SQL_EXECUTOR] Question received by generate_sql_query: {question}"
    )

    prompt = build_generation_prompt(question, schema_info)

    response = llm.invoke(
        prompt,
        config=config,
    )

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
async def execute_sql_query(
    sql_query: str,
    config: RunnableConfig,
    question: str = "",
):
    """Execute a validated SQL query. Auto-fix once if SQL execution fails."""

    query = validate_sql_query.invoke(sql_query)

    if query.startswith("Error:"):
        return _error_payload(
            f"Query validation failed: {query}"
        )

    try:
        payload = await _run_select(query)

        logger.info(
            "[SQL_EXECUTOR] Returned %s rows",
            payload["row_count"],
        )
        return _as_tool_payload(payload)

    except Exception as e:
        logger.error(f"[SQL_EXECUTOR] SQL execution failed: {e}")

        # fix_sql_error is a coroutine, so this must be awaited. It was
        # previously called with .invoke() from a synchronous tool, which
        # raises "StructuredTool does not support sync invocation" — so
        # every SQL execution error destroyed the whole SQL branch instead
        # of being repaired, and the retry machinery around it had never
        # actually run. The failure only surfaced when the generator first
        # produced a query with a bad column name.
        #
        # config is forwarded because fix_sql_error needs the LLM runtime;
        # without it get_llm_client raises "llm_runtime is missing".
        fixed_query = await fix_sql_error.ainvoke(
            {
                "original_query": query,
                "error_message": str(e),
                "question": question,
            },
            config=config,
        )

        fixed_query = validate_sql_query.invoke(fixed_query)

        if fixed_query.startswith("Error:"):
            return _error_payload(
                f"Fixed query validation failed: {fixed_query}"
            )

        try:
            payload = await _run_select(fixed_query)

            # payload["executed_sql"] is fixed_query, so the repair is
            # visible to state and to the evaluator instead of the caller
            # keeping a query that never ran.
            payload["auto_fixed"] = True
            payload["original_sql"] = query

            logger.info(
                "[SQL_EXECUTOR] Auto-fixed query returned %s rows "
                "(original failed: %s)",
                payload["row_count"],
                str(e)[:120],
            )
            return _as_tool_payload(payload)

        except Exception as final_error:
            logger.error(f"[SQL_EXECUTOR] Fixed SQL also failed: {final_error}")

            return _error_payload(
                "SQL execution failed after auto-fix. "
                f"Original error: {str(e)}. "
                f"Final error: {str(final_error)}."
            )

@tool
async def fix_sql_error(original_query: str, error_message: str, question: str, config: RunnableConfig,)-> str:
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
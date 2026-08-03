import logging

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field


logger = logging.getLogger(__name__)
llm = ChatOpenAI(model="gpt-5.4-mini", temperature=0)


class QueryPlan(BaseModel):
    sql_query: str = Field(
        description="Focused query for SQL financial metrics retrieval"
    )
    vector_query: str = Field(
        description="Focused query for vector document search"
    )
    market_query: str = Field(
        description=(
            "Comma separated tickers for live market data. "
            "Only for MIXED intent. Empty string for all others."
        )
    )
    strategy: str = Field(
        description="PARALLEL, SQL_FIRST or VECTOR_FIRST"
    )


def plan_query(query: str, intent: str) -> dict:
    """
    Decompose user query into focused subqueries
    for each retrieval branch.

    VALUATION  → sql_query only (PE, market cap, price metrics)
    GROWTH     → sql_query only (revenue growth, EPS, earnings)
    SENTIMENT  → vector_query only (news, filings, commentary)
    MIXED      → both sql_query + vector_query + market_query
    """
    try:
        llm_structured = llm.with_structured_output(QueryPlan)

        system = SystemMessage(content="""
            You are a financial query planner.

            Given a user query and its business intent, decompose into:
                1. sql_query    — focused query for financial metrics
                                    (PE ratio, EPS, revenue growth, market cap)
                2. vector_query — focused query for document search
                                    (earnings calls, SEC filings, news articles)
                3. market_query — comma separated tickers for live market data
                                  ONLY for MIXED intent
                                  Empty string for VALUATION, GROWTH, SENTIMENT
                4. strategy     — how to retrieve:
                                    PARALLEL     → run SQL + Vector + Market at the same time
                                    SQL_FIRST    → SQL results guide vector search
                                    VECTOR_FIRST → document context guides SQL filtering

            INTENT MEANINGS:
            VALUATION  → user wants price/value metrics    → SQL only
            GROWTH     → user wants growth/earnings metrics → SQL only
            SENTIMENT  → user wants news/opinions          → Vector only
            MIXED      → user wants both                   → SQL + Vector + Market

            EXAMPLES:

            Query: "Find undervalued AI companies with positive earnings sentiment"
            Intent: MIXED
            → sql_query:    "undervalued technology companies low PE ratio strong growth"
            → vector_query: "positive earnings sentiment artificial intelligence growth outlook"
            → market_query: "AI technology semiconductor companies live price trends"
            → strategy:     "PARALLEL"

            Query: "Find cheap tech stocks with low PE"
            Intent: VALUATION
            → sql_query:    "technology companies low PE ratio undervalued market cap"
            → vector_query: ""
            → strategy:     "SQL_FIRST"

            Query: "Show high growth companies with strong EPS"
            Intent: GROWTH
            → sql_query:    "high revenue growth strong EPS earnings performance"
            → vector_query: ""
            → strategy:     "SQL_FIRST"

            Query: "What did NVIDIA say about data centers in earnings?"
            Intent: SENTIMENT
            → sql_query:    ""
            → vector_query: "NVIDIA data center revenue growth earnings commentary"
            → strategy:     "VECTOR_FIRST"

            Query: "Low PE tech companies with positive AI news"
            Intent: MIXED
            → sql_query:    "technology companies low PE ratio undervalued"
            → vector_query: "positive artificial intelligence news sentiment"
            → market_query: "technology companies low PE positive AI sentiment price trends"
            → strategy:     "PARALLEL"
            """)

        response = llm_structured.invoke([
            system,
            HumanMessage(
                content=f"Query: {query}\nIntent: {intent}"
            )
        ])

        logger.info(
            f"[PLANNER] strategy: {response.strategy}, "
            f"sql_q: {response.sql_query[:50]}, "
            f"vector_q: {response.vector_query[:50]}, "
            f"market_q: {response.market_query[:50]} "
        )

        return {
            "sql_query":    response.sql_query,
            "vector_query": response.vector_query,
            "market_query": response.market_query,
            "strategy":     response.strategy
        }

    except Exception as e:
        logger.error(f"[PLANNER] Planning failed: {e}")
        return {
            "sql_query":   query if intent in ["VALUATION", "GROWTH", "MIXED"] else "",
            "vector_query": query if intent in ["SENTIMENT", "MIXED"] else "",
            "market_query": "",
            "strategy":     "PARALLEL"
        }


def planner_node(state: dict) -> dict:
    """LangGraph node for query planning."""
    query  = state["original_query"]
    intent = state["intent"]
    plan   = plan_query(query, intent)
    return {
        **state,
        "sql_query":    plan["sql_query"],
        "vector_query": plan["vector_query"],
        "market_query": plan["market_query"],
        "strategy":     plan["strategy"]
    }
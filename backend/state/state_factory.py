from __future__ import annotations

from langchain_core.messages import HumanMessage

from backend.state.financial_state import FinancialState


def build_initial_financial_state(
    query: str,
) -> FinancialState:
    """
    Build the initial LangGraph state.

    Both the regular financial route and the benchmark runner
    should use this helper so they always start with the
    exact same state.
    """

    query = query.strip()

    return {
        # Conversation
        "messages": [
            HumanMessage(content=query)
        ],
        "original_query": query,

        # Intent
        "intent": "",
        "intent_reason": "",

        # Planner
        "sql_query": "",
        "vector_query": "",
        "market_query": "",
        "strategy": "",

        # Retrieval
        "generated_sql": "",
        "sql_result": {},
        "vector_result": {},
        "market_result": {},

        # vector
        "retrieved_contexts": [],

        #reranker
        "reranked_contexts": [],
        "reranked_context_records": [],

        # Scoring
        "scoring_result": None,
        "ranked_companies": [],

        # Analysis
        "draft_report": None,
        "review_result": None,
        "final_report": None,

        # Retry
        "should_retry": False,
        "retry_count": 0,

        # Tool tracing
        "executed_tools": [],
    }
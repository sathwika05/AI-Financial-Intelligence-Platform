from __future__ import annotations

import operator
from typing import Annotated, Any, Optional, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages


class FinancialState(TypedDict):
    """
    Shared LangGraph state for the Financial Intelligence pipeline.

    Every node reads and writes only this state.
    """

    # Conversation
    messages: Annotated[
        list[BaseMessage],
        add_messages,
    ]
    original_query: str

    # Intent
    intent: str
    intent_reason: str

    # Planner
    sql_query: str
    vector_query: str
    market_query: str
    strategy: str

    # Candidate universe — who is eligible to be ranked, decided once and
    # shared by every retrieval branch.
    #
    # Without this each branch discovered its own set: SQL invented a filter
    # from document text and returned EOG/JPM/GS, while the market branch
    # resolved NVDA/MSFT/GOOGL/AMZN/META from the planner's wording. The
    # scorer then ranked the union, so an energy company could win a query
    # about AI.
    #
    # Empty means no theme was recognised, which is not an error — most
    # questions name no category and every company stays eligible.
    theme_slug: Optional[str]
    candidate_tickers: list[str]
    candidate_company_ids: list[int]

    # Retrieval outputs
    generated_sql: str
    sql_result: dict[str, Any]
    vector_result: dict[str, Any]
    market_result: dict[str, Any]

    # Evaluation artifacts
    retrieved_contexts: list[str]

    # Reranker - mixed
    reranked_contexts: list[str]
    reranked_context_records: list[dict[str, Any]]

    # Scoring
    scoring_result: Optional[dict[str, Any]]
    ranked_companies: list[dict[str, Any]]

    # Analysis
    draft_report: Optional[dict[str, Any]]
    review_result: Optional[dict[str, Any]]
    final_report: Optional[dict[str, Any]]

    # Retry
    should_retry: bool
    retry_count: int
    # Which stage a retry goes to, and the rejected claims handed to
    # analysis when the failure was a grounding problem.
    retry_target: str
    review_feedback: list[str]

    # Evaluation / tracing
    executed_tools: Annotated[
        list[str],
        operator.add,
    ]

    # Wall-clock time spent in each graph node, appended by the timing
    # wrapper in financial_graph. A reducer-backed list rather than a dict
    # because the reviewer can route back and run a node more than once, and
    # every pass is worth keeping — the aggregate averages them.
    node_timings: Annotated[
        list[dict[str, Any]],
        operator.add,
    ]

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

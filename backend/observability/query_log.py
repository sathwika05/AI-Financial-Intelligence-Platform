"""
One row per query, so operational questions have answers.

retrieval_logs has been in the schema since the beginning with no writer,
which meant every question about live traffic -- p95 latency, queries per
day, what share of answers gets withheld -- could only be answered "I
don't have that". system_logs holds text lines a person reads; no amount
of grep over prose produces a percentile.

The query is masked before it is stored, following security/events.py. In
portfolio mode this endpoint is public and unauthenticated, so what
people type is not assumed to be safe to keep, and a diagnostic table
should not quietly become a second copy of whatever was in it.

Nothing here may break a query. This is a diagnostic beside the answer,
not part of it, and a database that will not take the row must not turn a
completed pipeline run into a 500.
"""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import text

from backend.security.pii import PIIDetector
from backend.services.postgres_service import engine


logger = logging.getLogger(__name__)

_pii = PIIDetector()

# The request schema caps a query at 500 characters; this bounds a stored
# row even if that ever changes.
MAX_STORED_QUERY = 500


def build_row(
    *,
    query: str,
    final_report: Any,
    latency_ms: float,
) -> dict[str, Any]:
    """
    The row, separated from writing it so it can be tested without a
    database and so a malformed report cannot reach the insert.

    An absent intent records "unknown" rather than being dropped: a query
    that failed before classification is exactly the kind worth counting,
    and a missing row would make the totals disagree with reality.
    """
    report = final_report if isinstance(final_report, dict) else {}
    review = report.get("review")

    if not isinstance(review, dict):
        review = {}

    return {
        "query": _pii.mask(query or "")[:MAX_STORED_QUERY],
        "retrieval_path": str(report.get("intent") or "unknown"),
        "latency_ms": float(latency_ms),
        "decision": review.get("decision"),
    }


async def _insert(
    *,
    query: str,
    retrieval_path: str,
    latency_ms: float,
    decision: str | None,
) -> None:
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO retrieval_logs "
                "(query, retrieval_path, latency_ms, decision) "
                "VALUES (:query, :retrieval_path, :latency_ms, :decision)"
            ),
            {
                "query": query,
                "retrieval_path": retrieval_path,
                "latency_ms": latency_ms,
                "decision": decision,
            },
        )


async def record(
    *,
    query: str,
    final_report: Any,
    latency_ms: float,
) -> None:
    """Store one query's outcome. Never raises."""
    try:
        await _insert(**build_row(
            query=query,
            final_report=final_report,
            latency_ms=latency_ms,
        ))
    except Exception:
        logger.warning(
            "[QUERY_LOG] could not record the query; the request continues",
            exc_info=True,
        )

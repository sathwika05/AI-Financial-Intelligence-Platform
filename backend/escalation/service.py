"""
Reading and writing the escalation queue.

The reviewer decides what to withhold; this decides what to keep. The two
are separate because the reviewer runs inside the graph, where a database
session is not in scope and a failed write would take a user's query down
with it.
"""
import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.db_models import Escalation


logger = logging.getLogger(__name__)


# What an administrator can do with a row. "resolved" means they looked and
# accepted the outcome; "dismissed" means the escalation itself was noise.
# Both leave the pending queue; keeping them apart is what makes the queue
# worth reading a second time.
RESOLUTIONS = ("pending", "resolved", "dismissed")


async def record_escalation(
    session: AsyncSession,
    *,
    query: str,
    final_report: dict[str, Any] | None,
    draft_report: dict[str, Any] | None,
) -> Escalation | None:
    """
    File an escalation, if this report is one.

    Returns None for a healthy report. The caller runs this on every query
    and does not repeat the threshold — one condition, in one place.
    """
    review = (final_report or {}).get("review") or {}

    if not review.get("escalated"):
        return None

    try:
        confidence = float(
            (final_report or {}).get("overall_confidence") or 0.0
        )
    except (TypeError, ValueError):
        confidence = 0.0

    row = Escalation(
        query=query,
        intent=(final_report or {}).get("intent"),
        confidence=confidence,
        notice=review.get("notice"),
        withheld_report=draft_report or {},
        review_flags=review.get("flags") or [],
        status="pending",
    )

    session.add(row)
    await session.flush()

    logger.warning(
        "[ESCALATION] Withheld a report confidence=%.2f id=%s",
        confidence,
        row.id,
    )

    return row


async def list_escalations(
    session: AsyncSession,
    *,
    status: str | None = "pending",
    limit: int = 100,
) -> list[Escalation]:
    """Newest first: an admin opens the queue to see what just happened."""
    statement = select(Escalation)

    if status:
        statement = statement.where(Escalation.status == status)

    # id, not created_at. Rows written inside one second share a timestamp
    # at the database's resolution, and the queue then reorders itself
    # between refreshes.
    statement = statement.order_by(Escalation.id.desc()).limit(limit)

    result = await session.execute(statement)

    return list(result.scalars().all())


async def resolve_escalation(
    session: AsyncSession,
    *,
    escalation_id: int,
    status: str,
    note: str,
    reviewer: str,
) -> Escalation | None:
    """
    Close a row. Returns None if it does not exist, so the route can
    answer 404 rather than 500.
    """
    if status not in RESOLUTIONS:
        raise ValueError(
            f"Unknown resolution {status!r}; expected one of "
            f"{', '.join(RESOLUTIONS)}"
        )

    row = await session.get(Escalation, escalation_id)

    if row is None:
        return None

    row.status = status
    row.resolution_note = note or None
    row.reviewed_by = reviewer
    # Naive UTC: the column is TIMESTAMP WITHOUT TIME ZONE, and an
    # aware value fails to encode rather than being converted.
    row.reviewed_at = datetime.now(timezone.utc).replace(tzinfo=None)

    await session.flush()

    return row

"""
Reading and writing claim rows.

THE ONE RULE
    upsert_claims writes evaluator columns only. human_label,
    human_labeled_by and human_labeled_at are never in its update set, so
    re-running a benchmark over the same run replaces the judge's verdict
    and leaves the human's alone. Comparing the two is the whole point of
    the validation page, and it is impossible if either side can quietly
    overwrite the other.

Rows come back as plain dicts rather than ORM objects: every caller here
is either serialising to JSON for the dashboard or feeding metrics.py,
and neither wants a session-bound instance.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.evaluation.claims.audit import ClaimAudit
from backend.evaluation.claims.checker import LABELS
from backend.models.db_models import ClaimEvaluation, QuestionResult


# Columns the evaluator owns. Listed explicitly so that adding a human
# column later cannot accidentally join the update set.
_EVALUATOR_COLUMNS = (
    "route",
    "claim",
    "original",
    "is_numeric",
    "numeric_values",
    "evidence",
    "evaluator_label",
    "evaluator_reasoning",
    "evaluator_model",
)


def _as_dict(row: ClaimEvaluation, question: str | None = None) -> dict[str, Any]:
    return {
        # The question the claim came from, joined in rather than stored
        # per row. A claim cannot be labelled without it: "Chevron ranks
        # second" means nothing until you know what was asked.
        "question": question,
        "id": row.id,
        "run_id": str(row.run_id) if row.run_id else None,
        "question_id": row.question_id,
        "route": row.route,
        "claim_index": row.claim_index,
        "claim": row.claim,
        "original": row.original,
        "is_numeric": bool(row.is_numeric),
        "numeric_values": row.numeric_values or [],
        "evidence": row.evidence or [],
        "evaluator_label": row.evaluator_label,
        "evaluator_reasoning": row.evaluator_reasoning,
        "evaluator_model": row.evaluator_model,
        "human_label": row.human_label,
        "human_labeled_by": row.human_labeled_by,
        "human_labeled_at": (
            row.human_labeled_at.isoformat() if row.human_labeled_at else None
        ),
    }


async def upsert_claims(
    session: AsyncSession,
    *,
    run_id: UUID,
    question_id: str,
    route: str | None,
    audit: ClaimAudit,
) -> None:
    """
    Write one row per claim, updating in place on a re-run.

    Keyed on (run_id, question_id, claim_index), matching the table's
    unique constraint, so persisting a run twice updates rather than
    accumulating duplicates.
    """
    rows = audit.rows_for(
        run_id=run_id, question_id=question_id, route=route
    )

    if not rows:
        return

    existing = await session.execute(
        select(ClaimEvaluation).where(
            ClaimEvaluation.run_id == run_id,
            ClaimEvaluation.question_id == question_id,
        )
    )

    by_index = {row.claim_index: row for row in existing.scalars().all()}

    for values in rows:
        record = by_index.get(values["claim_index"])

        if record is None:
            session.add(ClaimEvaluation(**values))
            continue

        # Evaluator columns only — see the module docstring.
        for column in _EVALUATOR_COLUMNS:
            setattr(record, column, values[column])


def _filtered(
    query: Any,
    *,
    run_id: UUID,
    label: str | None,
    unlabeled: bool,
    labeled: bool,
) -> Any:
    """
    Apply the queue's filters to a select.

    Shared by the page and its count. Written once because the two
    drifting apart produces the worst version of this screen: a header
    promising rows that the list does not contain.
    """
    if labeled and unlabeled:
        raise ValueError(
            "labeled and unlabeled are complements; pass at most one"
        )

    query = query.where(ClaimEvaluation.run_id == run_id)

    if label:
        query = query.where(ClaimEvaluation.evaluator_label == label)

    if unlabeled:
        query = query.where(ClaimEvaluation.human_label.is_(None))

    if labeled:
        query = query.where(ClaimEvaluation.human_label.is_not(None))

    return query


async def claims_for_run(
    session: AsyncSession,
    *,
    run_id: UUID,
    label: str | None = None,
    unlabeled: bool = False,
    labeled: bool = False,
    offset: int = 0,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """
    One run's claims, ordered so a labelling session stays put.

    `labeled` and `unlabeled` are complements and cannot both be set. A
    caller passing both has a bug, and quietly returning nothing would
    hide it behind an empty screen.

    Ordered by question then claim index rather than by id: a re-run
    replaces rows in place, and ordering by id would reshuffle the page
    under someone halfway through labelling fifty of them.
    """
    query = _filtered(
        select(ClaimEvaluation),
        run_id=run_id,
        label=label,
        unlabeled=unlabeled,
        labeled=labeled,
    )

    query = query.order_by(
        ClaimEvaluation.question_id,
        ClaimEvaluation.claim_index,
    )

    if offset:
        query = query.offset(offset)

    if limit:
        query = query.limit(limit)

    # Outer join: a claim whose question row is missing — an older run, or
    # a persist that failed after the claims landed — must still load. The
    # caption is worth less than the claim.
    query = query.add_columns(QuestionResult.question).outerjoin(
        QuestionResult,
        (QuestionResult.run_id == ClaimEvaluation.run_id)
        & (QuestionResult.question_id == ClaimEvaluation.question_id),
    )

    result = await session.execute(query)

    return [_as_dict(row, question) for row, question in result.all()]


async def count_claims_for_run(
    session: AsyncSession,
    *,
    run_id: UUID,
    label: str | None = None,
    unlabeled: bool = False,
    labeled: bool = False,
) -> int:
    """
    How many claims match, ignoring the page.

    "Showing 1-25 of 1072" needs the 1072, and a page of 25 cannot supply
    it. Runs through the same _filtered helper as the page itself, so the
    count and the rows can never describe different sets.
    """
    query = _filtered(
        select(func.count()).select_from(ClaimEvaluation),
        run_id=run_id,
        label=label,
        unlabeled=unlabeled,
        labeled=labeled,
    )

    return int((await session.execute(query)).scalar_one())


async def save_human_label(
    session: AsyncSession,
    *,
    claim_id: int,
    label: str,
    labeled_by: str,
) -> dict[str, Any]:
    """
    Record a person's verdict, leaving the evaluator's in place.

    Refuses a label outside the three: an unrecognised value would be
    counted as a permanent disagreement by the agreement maths and would
    never match anything.
    """
    if label not in LABELS:
        raise ValueError(f"Unknown claim label: {label!r}")

    record = await session.get(ClaimEvaluation, claim_id)

    if record is None:
        raise LookupError(f"No claim with id {claim_id}")

    record.human_label = label
    record.human_labeled_by = labeled_by
    record.human_labeled_at = datetime.now(timezone.utc).replace(tzinfo=None)

    return _as_dict(record)

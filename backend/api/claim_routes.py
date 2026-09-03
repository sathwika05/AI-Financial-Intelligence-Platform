"""
Claim-level grounding, read and validated.

Admin-only, matching the rest of the evaluation surface. A claim row
carries the answer's own text and the evidence it was judged against,
which is more of the corpus than the analyst endpoints hand out.

The rates here are computed from rows on every request rather than stored
on evaluation_metrics. A stored aggregate goes stale the moment someone
relabels a claim, and relabelling is the entire purpose of the validation
page.
"""
from __future__ import annotations

import logging
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from backend.auth.dependencies import require_role
from backend.auth.roles import Role
from backend.evaluation.claims.checker import LABELS
from backend.evaluation.claims.metrics import agreement_stats, claim_rates
from backend.evaluation.claims.store import claims_for_run, save_human_label
from backend.services.postgres_service import get_db

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/evaluation",
    tags=["Claim Audit"],
    dependencies=[Depends(require_role(Role.ADMIN))],
)


class HumanLabelRequest(BaseModel):
    """
    One person's verdict on one claim.

    Literal rather than str: an unrecognised label would be counted as a
    permanent disagreement by the agreement maths and would never match
    anything, so it is refused at the edge with a 422 rather than stored.
    """

    human_label: Literal[
        "SUPPORTED",
        "UNSUPPORTED",
        "INSUFFICIENT_EVIDENCE",
    ]


@router.get("/runs/{run_id}/claims")
async def list_claims(
    run_id: UUID,
    label: str | None = Query(default=None),
    unlabeled: bool = Query(default=False),
    limit: int = Query(default=500, ge=1, le=2000),
    session: AsyncSession = Depends(get_db),
) -> list[dict]:
    """One run's claims, oldest question first, for the labelling queue."""
    if label and label not in LABELS:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown label {label!r}. Expected one of {list(LABELS)}.",
        )

    return await claims_for_run(
        session,
        run_id=run_id,
        label=label,
        unlabeled=unlabeled,
        limit=limit,
    )


@router.get("/runs/{run_id}/claims/summary")
async def claim_summary(
    run_id: UUID,
    session: AsyncSession = Depends(get_db),
) -> dict:
    """
    The run's claim rates, and how well the evaluator matched a human.

    Both sets come back together because the dashboard shows them on one
    row of cards, and because a support rate without an agreement figure
    beside it is just another LLM's opinion.
    """
    rows = await claims_for_run(session, run_id=run_id, limit=2000)

    return {**claim_rates(rows), **agreement_stats(rows)}


@router.patch("/claims/{claim_id}")
async def label_claim(
    claim_id: int,
    request: HumanLabelRequest,
    session: AsyncSession = Depends(get_db),
    user=Depends(require_role(Role.ADMIN)),
) -> dict:
    """Record a human verdict, leaving the evaluator's label in place."""
    try:
        updated = await save_human_label(
            session,
            claim_id=claim_id,
            label=request.human_label,
            # TokenClaims.subject is the signed-in address; the
            # dependency returns claims, not a User row.
            labeled_by=user.subject,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    await session.commit()

    logger.info(
        "[CLAIMS] Human label claim_id=%s label=%s",
        claim_id,
        request.human_label,
    )

    return updated

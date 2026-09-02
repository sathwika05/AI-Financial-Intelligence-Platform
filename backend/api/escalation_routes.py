"""
The human-in-the-loop queue.

One list and one decision. Everything else an administrator needs is in
the row itself — the question, the number that tripped the threshold, the
reviewer's flags, and the draft the analyst never saw.
"""
import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from backend.auth.dependencies import require_role
from backend.auth.roles import Role
from backend.auth.tokens import TokenClaims
from backend.escalation.service import (
    RESOLUTIONS,
    list_escalations,
    resolve_escalation,
)
from backend.models.db_models import Escalation
from backend.services.postgres_service import get_db


logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/admin/escalations",
    tags=["Human review"],
)


class ResolveRequest(BaseModel):
    # "pending" is accepted so a row opened by mistake can be put back.
    status: str = Field(pattern="^(pending|resolved|dismissed)$")
    note: str = Field(default="", max_length=2000)


def _serialize(row: Escalation) -> dict:
    return {
        "id": row.id,
        "query": row.query,
        "intent": row.intent,
        "confidence": row.confidence,
        "notice": row.notice,
        "withheld_report": row.withheld_report,
        "review_flags": row.review_flags or [],
        "status": row.status,
        "reviewed_by": row.reviewed_by,
        "resolution_note": row.resolution_note,
        "reviewed_at": (
            row.reviewed_at.isoformat() if row.reviewed_at else None
        ),
        "created_at": (
            row.created_at.isoformat() if row.created_at else None
        ),
    }


@router.get(
    "",
    dependencies=[Depends(require_role(Role.ADMIN))],
)
async def get_escalations(
    status: str = "pending",
    session: AsyncSession = Depends(get_db),
):
    """The queue, newest first. `status=all` reads the whole history."""
    if status != "all" and status not in RESOLUTIONS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unknown status {status!r}; expected 'all' or one of "
                f"{', '.join(RESOLUTIONS)}."
            ),
        )

    rows = await list_escalations(
        session,
        status=None if status == "all" else status,
    )

    return {
        "status": status,
        "count": len(rows),
        "escalations": [_serialize(row) for row in rows],
    }


@router.post("/{escalation_id}/resolve")
async def post_resolution(
    escalation_id: int,
    request: ResolveRequest,
    session: AsyncSession = Depends(get_db),
    # Claims rather than a body field: who reviewed this is taken from the
    # token, so it cannot be typed in as somebody else.
    claims: TokenClaims = Depends(require_role(Role.ADMIN)),
):
    """Record what the administrator decided."""
    row = await resolve_escalation(
        session,
        escalation_id=escalation_id,
        status=request.status,
        note=request.note,
        # subject is the user's email; see auth_routes.create_access_token.
        reviewer=claims.subject,
    )

    if row is None:
        raise HTTPException(
            status_code=404,
            detail=f"No escalation with id {escalation_id}.",
        )

    await session.commit()

    logger.info(
        "[ESCALATION] id=%s marked %s by %s",
        escalation_id,
        request.status,
        claims.subject,
    )

    return _serialize(row)

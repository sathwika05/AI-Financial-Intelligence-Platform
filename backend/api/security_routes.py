"""
The guard log, for the admin screen.

Read-only. The guards write these rows as a side effect of doing their
job; nothing here can change what they decided.
"""
import logging

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from backend.auth.dependencies import require_role
from backend.auth.roles import Role
from backend.security.events_feed import GUARDRAILS, read_security_events
from backend.services.postgres_service import get_db


logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/admin/security",
    tags=["Security"],
)


@router.get(
    "/events",
    dependencies=[Depends(require_role(Role.ADMIN))],
)
async def get_security_events(
    limit: int = 100,
    session: AsyncSession = Depends(get_db),
):
    """What the guards have caught, newest first."""
    events = await read_security_events(
        session,
        # Bounded here rather than trusted from the query string: the
        # screen polls, and an unbounded limit would have it re-reading
        # the whole table every few seconds.
        limit=max(1, min(limit, 200)),
    )

    return {
        "count": len(events),
        "events": events,
        # Sent alongside so the screen can render a legend without
        # hardcoding a second copy of the labels.
        "guardrails": GUARDRAILS,
    }

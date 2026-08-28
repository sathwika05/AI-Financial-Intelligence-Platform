"""Record what the security layers did, into system_logs.

Without this there is no way to tell a filter that is working from one that
never fires, or to find out that an analyst has been silently blocked for a
week.

The query is masked before it is stored. A record of a blocked input would
otherwise become a second copy of whatever personal data was in it.
"""
from __future__ import annotations

import json
import logging

from sqlalchemy import text

from backend.security.pii import PIIDetector
from backend.services.postgres_service import engine


logger = logging.getLogger(__name__)

_pii = PIIDetector()

# A query is capped at 500 characters by the request schema; this bounds
# what a log row can hold even so.
MAX_STORED_QUERY = 500


async def _insert(*, kind: str, detail: str, query: str) -> None:
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO system_logs (level, node, message, metadata) "
                "VALUES (:level, :node, :message, CAST(:metadata AS json))"
            ),
            {
                "level": "WARNING",
                "node": "security",
                "message": f"{kind}: {detail}",
                "metadata": json.dumps({"kind": kind, "query": query}),
            },
        )


async def record(*, kind: str, detail: str, query: str) -> None:
    """Store one security event. Never raises."""
    try:
        await _insert(
            kind=kind,
            detail=detail,
            query=_pii.mask(query or "")[:MAX_STORED_QUERY],
        )
    except Exception:
        logger.warning(
            "[SECURITY] could not record %s; the request continues",
            kind,
            exc_info=True,
        )

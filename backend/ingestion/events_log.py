"""
Recording what happened to each file.

The table is written on every attempt, not on every success. That is the
whole reason it exists: a duplicate, an unreadable PDF and a filing with
no readable text all leave the documents table untouched, so without this
they leave nothing at all.

Writing here must never fail an ingestion. A bookkeeping table that can
take down the work it is describing is worse than no table.
"""
from __future__ import annotations

import logging


logger = logging.getLogger(__name__)


# Closed set. A free-text status becomes six spellings of "failed" within
# a month, and then nothing can be counted.
OUTCOMES = (
    "indexed",     # stored and embedded
    "duplicate",   # the corpus already held it
    "unreadable",  # not a document this can parse
    "empty",       # parsed, but there was no text to index
    "failed",      # anything else, with the reason in detail
)


def stored_the_document(outcome: str) -> bool:
    """Whether this outcome means the corpus actually grew."""
    return outcome == "indexed"


async def record_attempt(
    *,
    source: str,
    reference: str,
    outcome: str,
    detail: str | None = None,
    document_id: int | None = None,
    chunks: int | None = None,
    session_factory=None,
) -> None:
    """
    Record one attempt. Never raises.

    The caller is in the middle of ingesting something; a failure to
    write this row is not a reason to fail that.
    """
    from backend.models.db_models import IngestionEvent
    from backend.services.postgres_service import AsyncSessionLocal

    factory = session_factory or AsyncSessionLocal

    try:
        async with factory() as session:
            session.add(
                IngestionEvent(
                    source=source,
                    reference=reference[:500],
                    outcome=outcome,
                    detail=detail[:2000] if detail else None,
                    document_id=document_id,
                    chunks=chunks,
                )
            )

            await session.commit()
    except Exception:
        logger.exception(
            "[INGEST] Could not record the %s attempt for %s", outcome, reference
        )

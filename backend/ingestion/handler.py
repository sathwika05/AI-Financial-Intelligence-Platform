"""
One object, from the queue to the corpus.

Reads the raw document S3 holds, writes it to the documents table, and
hands the row to the chunk -> embed -> store path that already exists.
That middle step is the one that was missing: until now the only writer to
documents was the seeding script, so an object landing in S3 had nowhere
to go.

The three collaborators are injected rather than imported so the decision
here -- what is worth indexing, and what a failure means -- is testable
without S3, Postgres, or the embedding API.
"""
from __future__ import annotations

import logging
from typing import Awaitable, Callable, Protocol

from backend.ingestion.events import ObjectRef


logger = logging.getLogger(__name__)


class SkippedObject(Exception):
    """
    The object was read but is not worth indexing.

    Distinct from a failure: the consumer treats this as handled and
    deletes the message, because a retry would skip it again.
    """


class Store(Protocol):
    async def get_json(self, bucket: str, key: str) -> dict: ...


Persist = Callable[[dict], Awaitable[int]]
Index = Callable[[int], Awaitable[None]]


async def handle_object(
    ref: ObjectRef,
    *,
    store: Store,
    persist: Persist,
    index: Index,
) -> None:
    """
    Read s3://bucket/key, store it, and index it.

    Raises SkippedObject when there is nothing to index, and lets every
    other failure propagate: the consumer decides whether to delete the
    message, and it can only decide correctly if the failure reaches it.
    """
    document = await store.get_json(ref.bucket, ref.key)

    content = (document.get("content") or "").strip()

    if not content:
        # Chunking empty text produces nothing, and embedding nothing is a
        # paid call that returns nothing.
        raise SkippedObject(
            f"s3://{ref.bucket}/{ref.key} has no content to index."
        )

    document_id = await persist(document)

    logger.info(
        "[INGEST] Stored s3://%s/%s as document %s",
        ref.bucket,
        ref.key,
        document_id,
    )

    await index(document_id)

    logger.info("[INGEST] Indexed document %s", document_id)

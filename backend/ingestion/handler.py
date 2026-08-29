"""
One object, from the queue to the corpus.

Reads what S3 holds, turns it into a document, writes that to the
documents table, and hands the row to the chunk -> embed -> store path
that already exists. That middle step is the one that was missing: until
now the only writer to documents was the seeding script, so an object
landing in S3 had nowhere to go.

Two kinds of object arrive, and the difference is the whole of the
dispatch below. A fetcher writes JSON, which already carries its own
title, ticker and content. Everything else -- an uploaded PDF, an EDGAR
filing in HTML -- arrives as bytes: the text has to be parsed out of a
laid-out document, and its provenance read off the key and the object's
own metadata.

The three collaborators are injected rather than imported so the decision
here -- what is worth indexing, and what a failure means -- is testable
without S3, Postgres, or the embedding API.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable, Protocol

from backend.ingestion.events import ObjectRef
from backend.ingestion.normalize import normalize_document
from backend.ingestion.publisher import metadata_from_key


logger = logging.getLogger(__name__)


class SkippedObject(Exception):
    """
    The object was read but is not worth indexing.

    Distinct from a failure: the consumer treats this as handled and
    deletes the message, because a retry would skip it again.
    """


class Store(Protocol):
    async def get_object(
        self, bucket: str, key: str
    ) -> tuple[bytes, dict]: ...

    async def get_json(self, bucket: str, key: str) -> dict: ...


Persist = Callable[[dict], Awaitable[int]]
Index = Callable[[int], Awaitable[None]]


# The formats Docling parses for us. The suffix is the only thing that
# says how to read an object, because S3 stores bytes and nothing else.
_PARSEABLE = (".pdf", ".htm", ".html")


def _needs_parsing(key: str) -> bool:
    return key.lower().endswith(_PARSEABLE)


async def _document_from_file(ref: ObjectRef, store: Store) -> dict:
    """
    A parseable object -- an uploaded PDF, an EDGAR filing -- as a document.

    Provenance comes from two places, and the order matters. The key
    always says something (source, ticker, a title from the filename),
    but a collector that knows more hangs it on the object as metadata:
    the filing URL that is its duplicate identity, the form, the date.
    Explicit metadata therefore wins, and a hand-uploaded file with none
    at all still indexes on what the key alone provides.

    Parsing is CPU-bound -- roughly a third of a second per document, far
    longer under OCR -- so it goes to a worker thread rather than blocking
    the loop that is also polling the queue.
    """
    from backend.ingestion.extract import UnreadableDocument, extract_text

    body, metadata = await store.get_object(ref.bucket, ref.key)
    filename = ref.key.rsplit("/", 1)[-1]

    try:
        text = await asyncio.to_thread(extract_text, body, filename=filename)
    except UnreadableDocument as exc:
        # Corrupt or password-protected. Neither becomes readable on the
        # tenth delivery, so this is a skip and not a failure: retrying
        # would hold the message until the redrive policy parks it, and
        # delay every document queued behind it.
        logger.error("[INGEST] s3://%s/%s: %s", ref.bucket, ref.key, exc)

        raise SkippedObject(
            f"s3://{ref.bucket}/{ref.key} could not be parsed."
        ) from exc

    document = dict(metadata_from_key(ref.key))

    # Only non-empty metadata overrides the key: S3 returns "" for an
    # absent value, and an empty ticker is worse than a derived one.
    document.update({k: v for k, v in (metadata or {}).items() if v})

    # A form says more than "filing", and doc_type is what the corpus is
    # filtered by.
    document["doc_type"] = document.get("form") or "filing"

    # Normalised here rather than after chunking, which would be too late:
    # the chunk boundaries would already have been drawn around the page
    # furniture.
    document["content"] = normalize_document(text)

    return document


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
    if _needs_parsing(ref.key):
        document = await _document_from_file(ref, store)
    else:
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

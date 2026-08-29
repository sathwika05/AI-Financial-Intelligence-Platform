"""
The ingestion worker: the ECS task that drains the queue.

    uv run python -m backend.ingestion.queue_worker

Terraform gives the task RAW_BUCKET, PROCESSED_BUCKET and
INGESTION_QUEUE_URL, plus a role that can read the bucket and consume the
queue. This is the process those were provisioned for.

It is a separate entrypoint rather than a thread inside the API, because
the two scale on different things: the API scales with people asking
questions, and this scales with documents arriving.
"""
from __future__ import annotations

import asyncio
import logging
import signal
from typing import Any, Awaitable, Callable

from sqlalchemy import select, update

from backend.ingestion.consumer import consume_once
from backend.ingestion.dedupe import find_duplicate_document, hash_content
from backend.ingestion.events import ObjectRef
from backend.ingestion.handler import SkippedObject, handle_object
from backend.ingestion.indexing_service import embed_document
from backend.models.db_models import Company, Document
from backend.services.postgres_service import AsyncSessionLocal


logger = logging.getLogger(__name__)


# Where a document is in its ingestion. Not read by retrieval -- these
# exist so a failed ingestion can be found and retried, rather than
# discovered by someone asking a question and getting nothing.
STATUS_PROCESSING = "processing"
STATUS_READY = "ready"


async def _existing_document(session, *, source_url, content_hash):
    """The row a duplicate check matched, so its status can be read."""
    if source_url:
        row = await session.scalar(
            select(Document).where(Document.source_url == source_url).limit(1)
        )

        if row is not None:
            return row

    if content_hash:
        return await session.scalar(
            select(Document).where(Document.content_hash == content_hash).limit(1)
        )

    return None


async def _mark_ready(document_id: int, *, session_factory=None) -> None:
    """
    Record that this document is indexed and retrievable.

    Called only after indexing returns without raising, which is the
    whole point: the gap between the row and its chunks is the state this
    column exists to name.
    """
    factory = session_factory or AsyncSessionLocal

    async with factory() as session:
        await session.execute(
            update(Document)
            .where(Document.id == document_id)
            .values(status=STATUS_READY)
        )

        await session.commit()


async def _raise_on_failed_index(
    document_id: int,
    *,
    embed: Callable[[int], Awaitable[dict[str, Any]]] = embed_document,
) -> None:
    """
    Turn embed_document's return value into an exception.

    It reports failure as {"success": False} rather than by raising. Handed
    to the consumer unchanged, a failed embed would look like success and
    the message would be deleted -- losing the document with no trace.
    """
    result = await embed(document_id)

    if not result.get("success"):
        raise RuntimeError(
            result.get("error") or f"Indexing document {document_id} failed."
        )


async def _persist_document(
    document: dict,
    *,
    session_factory=AsyncSessionLocal,
) -> int:
    """
    Write one raw document to the documents table.

    Raises SkippedObject when the corpus already holds it. That is not a
    failure: overwriting an object in S3 fires a second notification, the
    fetcher sees the same article on its next run, and a person re-uploads
    a filing they think did not work. Letting the insert hit the unique
    constraint instead would leave the message undeleted, redelivered, and
    eventually dead-lettered -- for a document already safely indexed.

    Resolves the ticker to a company where it can: a document with no
    company still indexes and is still retrievable, it just cannot be
    filtered by company.
    """
    async with session_factory() as session:
        content_hash = hash_content(document.get("content"))
        source_url = document.get("source_url")

        duplicate = await find_duplicate_document(
            session, source_url, content_hash
        )

        if duplicate:
            existing = await _existing_document(
                session, source_url=source_url, content_hash=content_hash
            )

            # A row whose indexing never finished is not a duplicate, it
            # is a retry. SQS redelivers a message whose work failed, and
            # by then the row exists; skipping it would delete the message
            # and strand the document in `processing` with no chunks and
            # nothing left to retry it.
            if existing is not None and existing.status != STATUS_READY:
                logger.info(
                    "[INGEST] Document %s is %s, not ready; reindexing it",
                    existing.id,
                    existing.status,
                )
                return existing.id

            raise SkippedObject(
                f"{document.get('title') or 'document'} is already in the "
                f"corpus (matched on {duplicate})."
            )

        company_id = None
        ticker = (document.get("ticker") or "").strip().upper()

        if ticker:
            company_id = await session.scalar(
                select(Company.id).where(Company.ticker == ticker)
            )

            if company_id is None:
                logger.warning(
                    "[INGEST] No company for ticker %s; storing the "
                    "document without one",
                    ticker,
                )

        row = Document(
            company_id=company_id,
            title=document.get("title"),
            content=document.get("content"),
            doc_type=document.get("doc_type") or "news",
            source=document.get("source") or "s3",
            source_url=source_url,
            # The identity the next delivery of this document is
            # recognised by. Without it, a re-upload has nothing to match.
            content_hash=content_hash,
            # Not ready: the row exists before a single chunk does, and
            # claiming otherwise is what made a failed ingestion invisible.
            status=STATUS_PROCESSING,
        )

        session.add(row)

        await session.commit()
        await session.refresh(row)

        return row.id


async def _handle(ref: ObjectRef, *, store) -> None:
    """One object, with SkippedObject swallowed so the message is deleted."""
    try:
        document_id = await handle_object(
            ref,
            store=store,
            persist=_persist_document,
            index=_raise_on_failed_index,
        )
    except SkippedObject as skipped:
        # Handled: a retry would skip it again, so the message should go.
        logger.info("[INGEST] %s", skipped)

        return

    # Only now, with indexing returned and nothing raised, is the document
    # actually retrievable.
    await _mark_ready(document_id)


async def run() -> None:
    from backend.ingestion.aws import ObjectStore, SqsQueue

    queue = SqsQueue()
    store = ObjectStore()

    stopping = asyncio.Event()

    # A stopping task must finish the message it is on. SIGTERM sets the
    # flag; the loop exits after the current poll rather than mid-delete,
    # which would redeliver work already done.
    loop = asyncio.get_running_loop()

    for received in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(received, stopping.set)

    logger.info("[INGEST] Worker polling %s", queue.queue_url)

    while not stopping.is_set():
        try:
            handled = await consume_once(
                queue=queue,
                handle=lambda ref: _handle(ref, store=store),
            )

            if handled:
                logger.info("[INGEST] Handled %s message(s)", handled)

        except Exception:
            # A poll that throws must not end the worker: the queue may be
            # briefly unreachable, and ECS restarting the task loses
            # nothing but adds a cold start.
            logger.exception("[INGEST] Poll failed; retrying in 5s")
            await asyncio.sleep(5)

    logger.info("[INGEST] Worker stopped")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run())

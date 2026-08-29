"""
A document says whether its indexing finished.

Before this, the row was written and then indexing ran, and nothing
recorded which of those succeeded. A document whose embedding call failed
looked exactly like one that worked -- a row with no chunks, which is
also what an empty document looks like -- so a failed ingestion was
discovered by someone asking a question and getting nothing back.

The interesting case is the second delivery. SQS redelivers a message
whose work failed, and by then the document row already exists. Treating
that as a duplicate would delete the message and leave the row stranded
in `processing` forever, with no chunks and nothing to retry it -- a
worse outcome than the failure it was meant to handle.
"""
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.db_models import Document
from backend.services.postgres_service import engine


FILING = "Apple reported revenue above consensus for the quarter."


@pytest.fixture
async def db():
    async with engine.connect() as connection:
        transaction = await connection.begin()
        session = AsyncSession(
            bind=connection, join_transaction_mode="create_savepoint"
        )
        try:
            yield session
        finally:
            await session.close()
            await transaction.rollback()


def _factory(session):
    class _Scope:
        async def __aenter__(self):
            return session

        async def __aexit__(self, *_exc):
            return False

    return lambda: _Scope()


class TestStatusOnTheWayIn:
    @pytest.mark.asyncio
    async def test_a_new_document_starts_as_processing(self, db):
        """
        Not 'ready'. The row exists before a single chunk does, and
        claiming otherwise is what made a failed ingestion invisible.
        """
        from backend.ingestion.queue_worker import _persist_document

        document_id = await _persist_document(
            {"title": "10-K", "content": FILING, "ticker": None},
            session_factory=_factory(db),
        )

        stored = await db.get(Document, document_id)

        assert stored.status == "processing"

    @pytest.mark.asyncio
    async def test_a_document_is_marked_ready_once_it_is_indexed(self, db):
        from backend.ingestion.queue_worker import _mark_ready, _persist_document

        document_id = await _persist_document(
            {"title": "10-K", "content": FILING, "ticker": None},
            session_factory=_factory(db),
        )

        await _mark_ready(document_id, session_factory=_factory(db))

        stored = await db.get(Document, document_id)

        assert stored.status == "ready"


class TestTheSecondDelivery:
    @pytest.mark.asyncio
    async def test_a_document_that_never_finished_is_retried(self, db):
        """
        The trap. The first delivery stored the row and then failed to
        embed, so the message comes back. The row is already there, and
        skipping it as a duplicate would delete the message and strand the
        document in `processing` with no chunks, permanently.
        """
        from backend.ingestion.dedupe import hash_content
        from backend.ingestion.queue_worker import _persist_document

        db.add(
            Document(
                title="10-K",
                content=FILING,
                doc_type="filing",
                source="manual",
                content_hash=hash_content(FILING),
                status="processing",
            )
        )
        await db.flush()

        # Must not raise: this is a retry, not a duplicate.
        document_id = await _persist_document(
            {"title": "10-K", "content": FILING, "ticker": None},
            session_factory=_factory(db),
        )

        assert document_id is not None

    @pytest.mark.asyncio
    async def test_the_retry_reuses_the_row_rather_than_adding_one(self, db):
        from backend.ingestion.dedupe import hash_content
        from backend.ingestion.queue_worker import _persist_document

        row = Document(
            title="10-K",
            content=FILING,
            doc_type="filing",
            source="manual",
            content_hash=hash_content(FILING),
            status="processing",
        )
        db.add(row)
        await db.flush()

        original_id = row.id

        document_id = await _persist_document(
            {"title": "10-K", "content": FILING, "ticker": None},
            session_factory=_factory(db),
        )

        assert document_id == original_id

        matching = await db.execute(
            select(Document).where(Document.content_hash == hash_content(FILING))
        )

        assert len(matching.scalars().all()) == 1

    @pytest.mark.asyncio
    async def test_a_document_that_did_finish_is_still_skipped(self, db):
        """
        The case the duplicate check exists for is unchanged.
        """
        from backend.ingestion.dedupe import hash_content
        from backend.ingestion.handler import SkippedObject
        from backend.ingestion.queue_worker import _persist_document

        db.add(
            Document(
                title="10-K",
                content=FILING,
                doc_type="filing",
                source="manual",
                content_hash=hash_content(FILING),
                status="ready",
            )
        )
        await db.flush()

        with pytest.raises(SkippedObject):
            await _persist_document(
                {"title": "10-K", "content": FILING, "ticker": None},
                session_factory=_factory(db),
            )

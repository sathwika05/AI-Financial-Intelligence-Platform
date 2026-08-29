"""
The worker must not reintroduce duplicates the seed works to avoid.

An uploaded object is not a one-off event. Overwriting a key in S3 fires
a second ObjectCreated, the fetcher writes the same article again on its
next scheduled run, and a person re-uploads a filing they think failed.
Every one of those arrives here as a fresh message.

Without a check, the second copy meets the unique constraint on
documents instead: the insert raises, the message is not deleted, it is
redelivered, it fails again, and it ends in the dead-letter queue -- for
a document already safely indexed. A duplicate is a skip, not a failure.

Run against the real table, because that is where the guarantee lives.
Each test owns a transaction that is rolled back, so the seeded database
is never modified.
"""
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.db_models import Document
from backend.services.postgres_service import engine


FILING = "Apple reported revenue above consensus for the quarter."


@pytest.fixture
async def db():
    """
    A session whose commits are undone.

    The session joins a transaction this fixture owns, so the code under
    test can commit exactly as it does in production while the outer
    rollback still discards everything.
    """
    async with engine.connect() as connection:
        transaction = await connection.begin()

        session = AsyncSession(
            bind=connection,
            join_transaction_mode="create_savepoint",
        )

        try:
            yield session
        finally:
            await session.close()
            await transaction.rollback()


def _factory(session):
    """A session factory that hands back the test's session."""

    class _Scope:
        async def __aenter__(self):
            return session

        async def __aexit__(self, *_exc):
            return False

    return lambda: _Scope()


class TestTheSameDocumentTwice:
    @pytest.mark.asyncio
    async def test_a_document_is_stored_with_its_content_hash(self):
        """
        The hash is the identity a re-upload is recognised by. Storing the
        row without one leaves nothing for the next delivery to match.
        """
        from backend.ingestion.dedupe import hash_content
        from backend.ingestion.queue_worker import _persist_document

        async with engine.connect() as connection:
            transaction = await connection.begin()
            session = AsyncSession(
                bind=connection, join_transaction_mode="create_savepoint"
            )

            try:
                document_id = await _persist_document(
                    {"title": "10-K", "content": FILING, "ticker": None},
                    session_factory=_factory(session),
                )

                stored = await session.get(Document, document_id)

                assert stored.content_hash == hash_content(FILING)
            finally:
                await session.close()
                await transaction.rollback()

    @pytest.mark.asyncio
    async def test_re_uploading_the_same_filing_is_skipped_not_failed(self, db):
        """
        Overwriting an object in S3 fires a second notification. Raising
        here would dead-letter a message for a document already indexed.
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
            )
        )
        await db.flush()

        with pytest.raises(SkippedObject):
            await _persist_document(
                {"title": "10-K", "content": FILING, "ticker": None},
                session_factory=_factory(db),
            )

    @pytest.mark.asyncio
    async def test_whitespace_alone_does_not_make_a_new_document(self, db):
        """
        Re-parsing the same PDF can re-wrap a line. That is not an
        editorial difference and must not produce a second copy.
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
            )
        )
        await db.flush()

        rewrapped = FILING.replace(" ", "\n  ", 1)

        with pytest.raises(SkippedObject):
            await _persist_document(
                {"title": "10-K", "content": rewrapped, "ticker": None},
                session_factory=_factory(db),
            )

    @pytest.mark.asyncio
    async def test_a_genuinely_different_filing_is_stored(self, db):
        from backend.ingestion.queue_worker import _persist_document

        document_id = await _persist_document(
            {
                "title": "10-Q",
                "content": "Gross margin expanded on a favourable services mix.",
                "ticker": None,
            },
            session_factory=_factory(db),
        )

        assert document_id is not None


class TestTheSeedAndTheWorkerAgree:
    def test_both_hash_a_document_the_same_way(self):
        """
        Two implementations of one identity would silently stop
        recognising each other's rows. There is only one, and this is the
        test that keeps it that way.
        """
        from seeds.seed_data import hash_content as seed_hash

        from backend.ingestion.dedupe import hash_content as worker_hash

        assert seed_hash is worker_hash

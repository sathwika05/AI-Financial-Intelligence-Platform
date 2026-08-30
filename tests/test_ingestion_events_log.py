"""
One row per file that was attempted, not per file that worked.

Everything visible today is an outcome: a documents row, a status, a
chunk count. A file that produced no row produced no trace either — a
duplicate, an unreadable PDF, a filing whose text could not be read, a
run that fetched nothing. Those are exactly the cases someone needs to
see, and they are the ones that vanish.

This records the attempt. Storing it is not conditional on the attempt
succeeding, which is the whole point.
"""
import pytest


class TestWhatAnOutcomeIs:
    def test_the_outcomes_are_closed(self):
        """
        A free-text status becomes six spellings of "failed". These are
        the states a file can end in, and there are not many.
        """
        from backend.ingestion.events_log import OUTCOMES

        assert set(OUTCOMES) == {
            "indexed",
            "duplicate",
            "unreadable",
            "empty",
            "failed",
        }

    def test_only_indexed_means_the_corpus_grew(self):
        from backend.ingestion.events_log import stored_the_document

        assert stored_the_document("indexed") is True

        for outcome in ("duplicate", "unreadable", "empty", "failed"):
            assert stored_the_document(outcome) is False


class TestRecording:
    @pytest.mark.asyncio
    async def test_a_successful_file_is_recorded_with_its_document(self, db):
        from backend.ingestion.events_log import record_attempt
        from backend.models.db_models import IngestionEvent

        await record_attempt(
            source="upload",
            reference="apple-10k.pdf",
            outcome="indexed",
            document_id=7,
            chunks=1447,
            session_factory=_factory(db),
        )

        row = (
            await db.execute(_for_reference(IngestionEvent, "apple-10k.pdf"))
        ).scalars().one()

        assert row.source == "upload"
        assert row.reference == "apple-10k.pdf"
        assert row.outcome == "indexed"
        assert row.document_id == 7
        assert row.chunks == 1447

    @pytest.mark.asyncio
    async def test_a_failure_is_recorded_with_its_reason(self, db):
        """
        The reason is the only thing that makes a failed row actionable.
        """
        from backend.ingestion.events_log import record_attempt
        from backend.models.db_models import IngestionEvent

        await record_attempt(
            source="upload",
            reference="notes.xlsx",
            outcome="unreadable",
            detail="Upload a PDF or an HTML filing.",
            session_factory=_factory(db),
        )

        row = (
            await db.execute(_for_reference(IngestionEvent, "notes.xlsx"))
        ).scalars().one()

        assert row.outcome == "unreadable"
        assert "PDF" in row.detail
        assert row.document_id is None

    @pytest.mark.asyncio
    async def test_recording_never_raises_into_the_caller(self, db):
        """
        This is bookkeeping. A logging table that can fail an ingestion is
        worse than no logging table.
        """
        from backend.ingestion.events_log import record_attempt

        def broken():
            raise RuntimeError("database is down")

        # Must not raise.
        await record_attempt(
            source="upload",
            reference="x.pdf",
            outcome="indexed",
            session_factory=broken,
        )


def _for_reference(model, reference: str):
    """
    The row this test wrote, not every row in the table.

    These assertions used to read the whole table, which passed only while
    it was empty -- the log is real now and outlives the suite by design.
    """
    from sqlalchemy import select

    return select(model).where(model.reference == reference)


def _factory(session):
    class _Scope:
        async def __aenter__(self):
            return session

        async def __aexit__(self, *_exc):
            return False

    return lambda: _Scope()


@pytest.fixture
async def db():
    from sqlalchemy.ext.asyncio import AsyncSession

    from backend.services.postgres_service import engine

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

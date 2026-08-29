"""
The database answer to "do we already have this filing?".

Until now this was a parameter the tests filled in. This is the real one,
and it is the thing that decides whether a download happens at all -- so
getting it wrong in the false direction re-downloads the whole archive
every run, and in the true direction silently collects nothing.

Run against the real table. Each test owns a transaction that is rolled
back, so the seeded database is never modified.
"""
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.db_models import Document
from backend.services.postgres_service import engine


FILING_URL = (
    "https://www.sec.gov/Archives/edgar/data/320193/"
    "000032019324000123/aapl-20240928.htm"
)


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


class TestWhatWeAlreadyHold:
    @pytest.mark.asyncio
    async def test_a_filing_we_have_is_recognised(self, db):
        from backend.ingestion.collector import stored_documents

        db.add(
            Document(
                title="AAPL 10-K",
                content="Apple reported revenue above consensus.",
                doc_type="10-K",
                source="sec_edgar",
                source_url=FILING_URL,
            )
        )
        await db.flush()

        already_have = stored_documents(session_factory=_factory(db))

        assert await already_have(FILING_URL) is True

    @pytest.mark.asyncio
    async def test_a_filing_we_have_never_seen_is_not(self, db):
        from backend.ingestion.collector import stored_documents

        already_have = stored_documents(session_factory=_factory(db))

        assert await already_have(FILING_URL) is False

    @pytest.mark.asyncio
    async def test_a_different_filing_from_the_same_company_is_not(self, db):
        """
        The accession number is what distinguishes them. Matching on the
        company would collect one filing and skip every later one.
        """
        from backend.ingestion.collector import stored_documents

        db.add(
            Document(
                title="AAPL 10-Q",
                content="Gross margin expanded.",
                doc_type="10-Q",
                source="sec_edgar",
                source_url=(
                    "https://www.sec.gov/Archives/edgar/data/320193/"
                    "000032019324000081/aapl-20240629.htm"
                ),
            )
        )
        await db.flush()

        already_have = stored_documents(session_factory=_factory(db))

        assert await already_have(FILING_URL) is False

"""
Database-backed deduplication.

These exercise the real `documents` table rather than an in-memory stand-in,
because that is where the guarantee lives: the seed checks before inserting,
but the unique constraints are what stop any other writer reintroducing a
duplicate.

Every test runs inside a transaction that is rolled back, so the seeded
database is never modified.
"""
import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from backend.models.db_models import Company, Document, DocumentChunk
from backend.services.postgres_service import AsyncSessionLocal
from seeds.seed_data import (
    canonicalize_url,
    find_duplicate_document,
    hash_content,
)


AMD_ARTICLE = (
    "Advanced Micro Devices Inc. is planning to raise as much $5 billion "
    "in what could be the chipmaker's biggest-ever investment-grade bond sale."
)


@pytest.fixture
async def db():
    """A session whose work is always rolled back."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.rollback()


@pytest.fixture
async def company(db):
    """A throwaway company to own the test documents."""
    row = Company(
        name="Test Chipmaker, Inc.",
        ticker="ZZTEST",
        sector="Technology",
        market_cap=1.0,
    )
    db.add(row)
    await db.flush()
    return row


async def _add_document(db, company, *, url, content, relevance=None):
    doc = Document(
        company_id=company.id,
        title="t",
        content=content,
        doc_type="news",
        source="Bloomberg",
        source_url=canonicalize_url(url),
        content_hash=hash_content(content),
        relevance_score=relevance,
    )
    db.add(doc)
    await db.flush()
    return doc


class TestDuplicateDetection:
    async def test_new_article_is_not_a_duplicate(self, db, company):
        reason = await find_duplicate_document(
            db,
            canonicalize_url("https://ex.com/brand-new"),
            hash_content("Entirely unseen content for this test."),
        )
        assert reason is None

    async def test_same_url_is_a_duplicate(self, db, company):
        await _add_document(
            db, company, url="https://ex.com/amd", content=AMD_ARTICLE
        )

        reason = await find_duplicate_document(
            db,
            canonicalize_url("https://ex.com/amd"),
            hash_content("Different text entirely, only the URL repeats."),
        )
        assert reason == "url"

    async def test_tracking_parameters_do_not_defeat_url_matching(
        self, db, company
    ):
        """The same link shared through a campaign is the same article."""
        await _add_document(
            db, company, url="https://ex.com/amd", content=AMD_ARTICLE
        )

        reason = await find_duplicate_document(
            db,
            canonicalize_url(
                "https://ex.com/amd?utm_source=newsletter&utm_medium=email"
            ),
            hash_content("Different text entirely."),
        )
        assert reason == "url"

    async def test_same_content_under_a_different_url_is_a_duplicate(
        self, db, company
    ):
        """
        The syndicated-newswire case: one story republished by several
        outlets, which is most of this corpus.
        """
        await _add_document(
            db, company, url="https://a.com/story", content=AMD_ARTICLE
        )

        reason = await find_duplicate_document(
            db,
            canonicalize_url("https://b.com/totally-different-path"),
            hash_content(AMD_ARTICLE),
        )
        assert reason == "content_hash"

    async def test_whitespace_variation_still_matches_by_hash(self, db, company):
        await _add_document(
            db, company, url="https://a.com/story", content=AMD_ARTICLE
        )

        reason = await find_duplicate_document(
            db,
            canonicalize_url("https://b.com/other"),
            hash_content(f"  {AMD_ARTICLE.replace(' ', '  ')}  "),
        )
        assert reason == "content_hash"

    async def test_article_without_url_still_deduped_by_content(
        self, db, company
    ):
        await _add_document(db, company, url=None, content=AMD_ARTICLE)

        reason = await find_duplicate_document(
            db,
            None,
            hash_content(AMD_ARTICLE),
        )
        assert reason == "content_hash"


class TestNoSecondRowIsWritten:
    async def test_the_regression_one_article_five_tickers(self, db, company):
        """
        The bug in miniature: the AMD article came back for AMD, JPM, BAC,
        MS and C, and each query wrote its own row. Running the seed's
        insert decision for all five must leave exactly one document.
        """
        canonical = canonicalize_url("https://ex.com/amd-bond-sale")
        digest = hash_content(AMD_ARTICLE)

        written = 0

        for _ in ("AMD", "JPM", "BAC", "MS", "C"):
            if await find_duplicate_document(db, canonical, digest):
                continue

            await _add_document(
                db, company, url="https://ex.com/amd-bond-sale",
                content=AMD_ARTICLE,
            )
            written += 1

        assert written == 1

        total = await db.execute(
            select(func.count())
            .select_from(Document)
            .where(Document.content_hash == digest)
        )
        assert total.scalar_one() == 1

    async def test_duplicate_creates_no_chunks(self, db, company):
        """
        A document that is never inserted has no id, so
        load_unindexed_documents() cannot return it and the indexing
        service never chunks or embeds it.
        """
        digest = hash_content(AMD_ARTICLE)
        doc = await _add_document(
            db, company, url="https://ex.com/amd", content=AMD_ARTICLE
        )

        # The duplicate attempt is rejected before a Document exists.
        assert await find_duplicate_document(
            db, canonicalize_url("https://ex.com/amd"), digest
        ) == "url"

        doc_ids = await db.execute(
            select(Document.id).where(Document.content_hash == digest)
        )
        ids = list(doc_ids.scalars().all())
        assert ids == [doc.id]

        chunks = await db.execute(
            select(func.count())
            .select_from(DocumentChunk)
            .where(DocumentChunk.document_id.in_(ids))
        )
        assert chunks.scalar_one() == 0


class TestDatabaseConstraints:
    async def test_unique_url_is_enforced_by_the_database(self, db, company):
        """
        The durable guarantee: even a writer that skips the seed's check
        cannot create a duplicate.
        """
        await _add_document(
            db, company, url="https://ex.com/unique-test", content=AMD_ARTICLE
        )

        db.add(
            Document(
                company_id=company.id,
                content="Different content, same URL.",
                doc_type="news",
                source="Reuters",
                source_url=canonicalize_url("https://ex.com/unique-test"),
                content_hash=hash_content("Different content, same URL."),
            )
        )

        with pytest.raises(IntegrityError):
            await db.flush()

    async def test_unique_content_hash_is_enforced_by_the_database(
        self, db, company
    ):
        await _add_document(
            db, company, url="https://ex.com/one", content=AMD_ARTICLE
        )

        db.add(
            Document(
                company_id=company.id,
                content=AMD_ARTICLE,
                doc_type="news",
                source="Reuters",
                source_url=canonicalize_url("https://ex.com/two"),
                content_hash=hash_content(AMD_ARTICLE),
            )
        )

        with pytest.raises(IntegrityError):
            await db.flush()

    async def test_multiple_documents_may_have_no_url(self, db, company):
        """
        Postgres allows repeated NULLs in a unique index, so articles
        without a URL must not collide with each other.
        """
        await _add_document(db, company, url=None, content="First body text.")
        await _add_document(db, company, url=None, content="Second body text.")

        rows = await db.execute(
            select(func.count())
            .select_from(Document)
            .where(Document.source_url.is_(None))
            .where(Document.company_id == company.id)
        )
        assert rows.scalar_one() == 2

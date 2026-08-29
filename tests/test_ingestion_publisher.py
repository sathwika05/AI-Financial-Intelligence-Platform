"""
The producer end: fetched documents land in S3.

Writing the object is what starts the whole path — the bucket notification
turns ObjectCreated into a queue message, and the worker does the rest. So
the key matters: two documents that collide overwrite each other, and one
that changes shape breaks the prefix everything else is grouped under.
"""
import pytest


class TestObjectKeys:
    def test_the_key_is_grouped_by_source_and_ticker(self):
        from backend.ingestion.publisher import object_key

        key = object_key(
            source="alpha_vantage",
            ticker="AAPL",
            identifier="abc123",
        )

        assert key == "alpha_vantage/AAPL/abc123.json"

    def test_a_document_with_no_ticker_still_gets_a_key(self):
        """Market-wide news belongs to no company but is still a document."""
        from backend.ingestion.publisher import object_key

        key = object_key(
            source="alpha_vantage",
            ticker=None,
            identifier="abc123",
        )

        assert key == "alpha_vantage/_unassigned/abc123.json"

    def test_identifiers_are_made_safe_for_a_key(self):
        """
        Identifiers come from a third party. A slash would silently create
        a prefix, and a space arrives URL-encoded, so both are replaced
        rather than trusted.
        """
        from backend.ingestion.publisher import object_key

        key = object_key(
            source="alpha_vantage",
            ticker="AAPL",
            identifier="2026/Q3 earnings?v=1",
        )

        assert "/" not in key.split("/")[-1]
        assert " " not in key
        assert "?" not in key

    def test_the_same_document_produces_the_same_key(self):
        """
        Re-fetching must overwrite rather than accumulate: the fetcher runs
        on a schedule and sees the same article repeatedly.
        """
        from backend.ingestion.publisher import object_key

        first = object_key(source="av", ticker="MSFT", identifier="xyz")
        second = object_key(source="av", ticker="MSFT", identifier="xyz")

        assert first == second


class TestPublishing:
    @pytest.mark.asyncio
    async def test_a_document_is_written_under_its_key(self):
        from backend.ingestion.publisher import publish_document

        store = _FakeStore()

        key = await publish_document(
            store=store,
            source="alpha_vantage",
            ticker="AAPL",
            identifier="abc",
            document={"title": "T", "content": "body"},
        )

        assert key == "alpha_vantage/AAPL/abc.json"
        assert store.written[key]["content"] == "body"

    @pytest.mark.asyncio
    async def test_the_source_and_ticker_travel_with_the_document(self):
        """
        The worker reads only the object, so anything the key encodes has
        to be in the body too or it is lost by the time it is stored.
        """
        from backend.ingestion.publisher import publish_document

        store = _FakeStore()

        key = await publish_document(
            store=store,
            source="alpha_vantage",
            ticker="AAPL",
            identifier="abc",
            document={"title": "T", "content": "body"},
        )

        written = store.written[key]

        assert written["source"] == "alpha_vantage"
        assert written["ticker"] == "AAPL"

    @pytest.mark.asyncio
    async def test_an_empty_document_is_refused_before_the_write(self):
        """
        An object with no content still fires a notification, still costs a
        message, and is skipped at the far end. Cheaper to refuse here.
        """
        from backend.ingestion.publisher import publish_document

        store = _FakeStore()

        with pytest.raises(ValueError):
            await publish_document(
                store=store,
                source="av",
                ticker="AAPL",
                identifier="abc",
                document={"title": "T", "content": "   "},
            )

        assert store.written == {}


class _FakeStore:
    def __init__(self):
        self.written: dict[str, dict] = {}

    async def put_json(self, key: str, payload: dict) -> None:
        self.written[key] = payload

"""
Collecting every recent filing for a ticker.

The step that turns the pieces into something runnable: resolve the
company, list its filings, and collect each one. Everything it calls is
already tested on its own; what is tested here is the sequence, and the
one decision the sequence has to make -- what happens when a single
filing fails.
"""
import json

import pytest


COMPANY_TICKERS = {"0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."}}

SUBMISSIONS = {
    "cik": "320193",
    "filings": {
        "recent": {
            "accessionNumber": [
                "0000320193-24-000123",
                "0000320193-24-000081",
                "0000320193-24-000070",
            ],
            "filingDate": ["2024-11-01", "2024-08-02", "2024-05-03"],
            "form": ["10-K", "10-Q", "8-K"],
            "primaryDocument": ["a.htm", "b.htm", "c.htm"],
        }
    },
}

FILING_HTML = b"<html><body><p>Apple reported revenue above consensus.</p></body></html>"


class TestCollectingForATicker:
    @pytest.mark.asyncio
    async def test_every_matching_filing_is_collected(self):
        from backend.ingestion.collector import collect_filings

        store = _FakeStore()

        keys = await collect_filings(
            "AAPL",
            store=store,
            fetch=_fetch(),
            already_have=_never(),
            forms=("10-K", "10-Q"),
        )

        assert len(keys) == 2
        assert all(key.startswith("sec_edgar/AAPL/") for key in keys)
        assert set(keys) == set(store.written)

    @pytest.mark.asyncio
    async def test_forms_not_asked_for_are_left_alone(self):
        """An 8-K is a press release, and it is in the same index."""
        from backend.ingestion.collector import collect_filings

        store = _FakeStore()

        await collect_filings(
            "AAPL",
            store=store,
            fetch=_fetch(),
            already_have=_never(),
            forms=("10-K",),
        )

        assert len(store.written) == 1

    @pytest.mark.asyncio
    async def test_filings_already_held_are_not_collected_again(self):
        from backend.ingestion.collector import collect_filings

        store = _FakeStore()

        keys = await collect_filings(
            "AAPL", store=store, fetch=_fetch(), already_have=_always()
        )

        assert keys == []
        assert store.written == {}

    @pytest.mark.asyncio
    async def test_one_bad_filing_does_not_abandon_the_rest(self):
        """
        Partial progress is worth keeping. Ten filings and one 404 should
        leave nine documents collected, not none -- and the next run picks
        up the one that failed, because it was never recorded as held.
        """
        from backend.ingestion.collector import collect_filings

        store = _FakeStore()

        async def fetch(url, *, headers=None):
            if url.endswith("company_tickers.json"):
                return json.dumps(COMPANY_TICKERS).encode()
            if "submissions" in url:
                return json.dumps(SUBMISSIONS).encode()
            if url.endswith("/a.htm"):
                raise RuntimeError("404 from EDGAR")
            return FILING_HTML

        keys = await collect_filings(
            "AAPL",
            store=store,
            fetch=fetch,
            already_have=_never(),
            forms=("10-K", "10-Q"),
        )

        assert len(keys) == 1
        assert "0000320193-24-000081" in keys[0]

    @pytest.mark.asyncio
    async def test_an_unknown_ticker_is_reported(self):
        """
        A typo should say so, not return an empty list that reads like
        "this company has filed nothing".
        """
        from backend.ingestion.collector import collect_filings
        from backend.ingestion.edgar import UnknownCompany

        with pytest.raises(UnknownCompany):
            await collect_filings(
                "NOTREAL",
                store=_FakeStore(),
                fetch=_fetch(),
                already_have=_never(),
            )

    @pytest.mark.asyncio
    async def test_the_limit_is_respected(self):
        from backend.ingestion.collector import collect_filings

        store = _FakeStore()

        keys = await collect_filings(
            "AAPL",
            store=store,
            fetch=_fetch(),
            already_have=_never(),
            forms=("10-K", "10-Q"),
            limit=1,
        )

        assert len(keys) == 1


def _fetch():
    async def fetch(url, *, headers=None):
        if url.endswith("company_tickers.json"):
            return json.dumps(COMPANY_TICKERS).encode()
        if "submissions" in url:
            return json.dumps(SUBMISSIONS).encode()
        return FILING_HTML

    return fetch


def _never():
    async def already_have(_url):
        return False

    return already_have


def _always():
    async def already_have(_url):
        return True

    return already_have


class _FakeStore:
    def __init__(self):
        self.written = {}

    async def put_bytes(self, key, body, *, content_type=None, metadata=None):
        self.written[key] = {"body": body, "metadata": metadata or {}}

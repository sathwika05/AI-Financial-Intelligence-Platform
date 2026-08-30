"""
Indexing an EDGAR filing without a bucket.

The lookup could list filings and do nothing with them, which made it a
dead end for the one thing it exists to serve: getting filings into the
corpus. The collector writes to S3 and needs a bucket; this downloads the
filing and indexes it in the same request, exactly as an uploaded file is
handled, so the path works on a laptop.

The client sends the filing's identifiers, never a URL. The URL is rebuilt
here and validated, so no caller can point this at a host of their
choosing and have the result stored as a filing.
"""
import pytest


FILING_HTML = (
    b"<html><body><h1>Item 1. Business</h1>"
    b"<p>Apple reported revenue above consensus.</p></body></html>"
)


def _filing_fields(**overrides) -> dict:
    fields = {
        "cik": "0000320193",
        "accession": "0000320193-24-000123",
        "form": "10-K",
        "filing_date": "2024-11-01",
        "primary_document": "aapl-20240928.htm",
        "ticker": "AAPL",
    }
    fields.update(overrides)
    return fields


class TestBuildingTheDocument:
    @pytest.mark.asyncio
    async def test_the_filing_is_downloaded_and_parsed(self):
        from backend.api.ingestion_routes import _prepare_edgar_filing

        async def fetch(url, *, headers=None):
            return FILING_HTML

        document = await _prepare_edgar_filing(
            _filing_fields(), fetch=fetch, headers={}
        )

        assert "revenue above consensus" in document["content"]

    @pytest.mark.asyncio
    async def test_the_provenance_matches_what_the_collector_would_store(self):
        """
        A filing indexed from this screen and the same filing arriving
        through S3 must become the same row, or the corpus holds two
        copies that no duplicate check can see are one.
        """
        from backend.api.ingestion_routes import _prepare_edgar_filing

        async def fetch(url, *, headers=None):
            return FILING_HTML

        document = await _prepare_edgar_filing(
            _filing_fields(), fetch=fetch, headers={}
        )

        assert document["source"] == "sec_edgar"
        assert document["ticker"] == "AAPL"
        assert document["doc_type"] == "10-K"
        assert "000032019324000123" in document["source_url"]
        assert document["title"] == "AAPL 10-K 2024-11-01"

    @pytest.mark.asyncio
    async def test_the_url_is_rebuilt_here_not_taken_from_the_client(self):
        """
        Whatever a caller sends, the request goes to sec.gov. Accepting a
        URL would let anyone store the contents of any host as a filing.
        """
        from backend.api.ingestion_routes import _prepare_edgar_filing

        asked = []

        async def fetch(url, *, headers=None):
            asked.append(url)
            return FILING_HTML

        await _prepare_edgar_filing(
            _filing_fields(source_url="https://evil.example/x.htm"),
            fetch=fetch,
            headers={},
        )

        assert asked[0].startswith("https://www.sec.gov/Archives/")
        assert "evil.example" not in asked[0]

    @pytest.mark.asyncio
    async def test_a_filing_with_no_readable_text_is_a_bad_request(self):
        from fastapi import HTTPException

        from backend.api.ingestion_routes import _prepare_edgar_filing

        async def fetch(url, *, headers=None):
            return b"<html><body></body></html>"

        with pytest.raises(HTTPException) as caught:
            await _prepare_edgar_filing(_filing_fields(), fetch=fetch, headers={})

        assert caught.value.status_code == 400

    @pytest.mark.asyncio
    async def test_edgar_refusing_the_download_is_reported_as_such(self):
        from fastapi import HTTPException

        from backend.api.ingestion_routes import _prepare_edgar_filing

        async def fetch(url, *, headers=None):
            raise RuntimeError("403 from EDGAR")

        with pytest.raises(HTTPException) as caught:
            await _prepare_edgar_filing(_filing_fields(), fetch=fetch, headers={})

        assert caught.value.status_code == 502


class TestTheRoute:
    def test_it_is_mounted_and_admin_only(self):
        from backend.auth.roles import Role
        from backend.main import build_app

        app = build_app(deployment_mode="full")

        routes = [
            r for r in app.routes
            if getattr(r, "path", "") == "/api/ingestion/edgar/documents"
        ]

        assert routes, "the EDGAR index route is not mounted"

        for route in routes:
            required = [
                getattr(d.call, "__required_role__", None)
                for d in route.dependant.dependencies
            ]
            assert Role.ADMIN in required

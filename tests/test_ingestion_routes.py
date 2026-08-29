"""
The endpoints behind the Ingestion screen.

Two of the three work with no AWS at all, which is the point: the S3 path
cannot be exercised on a laptop, but the two things most likely to be
wrong -- what EDGAR actually returns, and whether Docling can read the
file you have -- can be.

  GET  /api/ingestion/edgar/filings   read-only, needs only a User-Agent
  POST /api/ingestion/documents       parse and index one uploaded file
  GET  /api/ingestion/documents       what is in the corpus, and its status

All three are admin-only and none exist on the public deployment.
"""
import pytest

from backend.auth.roles import Role


class TestTheRoutesAreGuarded:
    def test_every_ingestion_route_requires_admin(self):
        """
        Uploading a document writes to the corpus and spends embedding
        credit; listing it exposes what the corpus holds.
        """
        from backend.main import build_app

        app = build_app(deployment_mode="full")

        guarded = [
            route
            for route in app.routes
            if getattr(route, "path", "").startswith("/api/ingestion")
        ]

        assert guarded, "no ingestion routes are mounted"

        for route in guarded:
            required = [
                getattr(d.call, "__required_role__", None)
                for d in route.dependant.dependencies
            ]

            assert Role.ADMIN in required, f"{route.path} is not admin-only"

    def test_they_are_absent_from_the_public_deployment(self):
        """
        Preprod is unauthenticated. A route that writes to the corpus must
        not be there to call.
        """
        from backend.main import build_app

        app = build_app(deployment_mode="portfolio")

        paths = {getattr(r, "path", "") for r in app.routes}

        assert not [p for p in paths if p.startswith("/api/ingestion")]


class TestUploadingADocument:
    @pytest.mark.asyncio
    async def test_a_readable_file_is_accepted(self):
        from backend.api.ingestion_routes import _prepare_upload

        raw = (
            b"<html><body><h1>Item 1. Business</h1>"
            b"<p>Apple reported revenue above consensus.</p></body></html>"
        )

        document = await _prepare_upload(
            filename="aapl-10k.htm", body=raw, ticker="AAPL"
        )

        assert "revenue above consensus" in document["content"]
        assert document["ticker"] == "AAPL"
        assert document["title"] == "aapl-10k"

    @pytest.mark.asyncio
    async def test_an_unreadable_file_is_a_bad_request_not_a_crash(self):
        """
        Someone will upload the wrong file. That is a 400 with a reason,
        not a 500 and a stack trace in the log.
        """
        from fastapi import HTTPException

        from backend.api.ingestion_routes import _prepare_upload

        with pytest.raises(HTTPException) as caught:
            await _prepare_upload(
                filename="notes.pdf", body=b"not a pdf at all", ticker=None
            )

        assert caught.value.status_code == 400

    @pytest.mark.asyncio
    async def test_an_unsupported_extension_is_refused_before_parsing(self):
        """
        Cheaper to refuse by name than to load a layout model and fail.
        """
        from fastapi import HTTPException

        from backend.api.ingestion_routes import _prepare_upload

        with pytest.raises(HTTPException) as caught:
            await _prepare_upload(
                filename="numbers.xlsx", body=b"anything", ticker=None
            )

        assert caught.value.status_code == 400
        assert "pdf" in caught.value.detail.lower()


class TestPreviewingEdgar:
    @pytest.mark.asyncio
    async def test_filings_are_listed_for_a_ticker(self):
        import json

        from backend.api.ingestion_routes import _preview

        async def fetch(url, *, headers=None):
            if url.endswith("company_tickers.json"):
                return json.dumps(
                    {"0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple"}}
                ).encode()
            return json.dumps(
                {
                    "filings": {
                        "recent": {
                            "accessionNumber": ["0000320193-24-000123"],
                            "filingDate": ["2024-11-01"],
                            "form": ["10-K"],
                            "primaryDocument": ["aapl.htm"],
                        }
                    }
                }
            ).encode()

        filings = await _preview(
            "AAPL", forms=("10-K",), limit=5, fetch=fetch, headers={}
        )

        assert filings[0]["form"] == "10-K"
        assert filings[0]["filing_date"] == "2024-11-01"
        assert filings[0]["url"].startswith("https://www.sec.gov/Archives/")

    @pytest.mark.asyncio
    async def test_an_unset_user_agent_is_a_clear_refusal(self):
        """
        SEC rejects anonymous requests. Saying so beats a 502 from EDGAR.
        """
        from fastapi import HTTPException

        from backend.api.ingestion_routes import _edgar_headers

        with pytest.raises(HTTPException) as caught:
            _edgar_headers("")

        assert caught.value.status_code == 503
        assert "SEC_USER_AGENT" in caught.value.detail

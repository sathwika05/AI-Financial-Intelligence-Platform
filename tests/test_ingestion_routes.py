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


# The upload behaviour these once covered has moved.
#
# _prepare_upload did the parsing inside the request and raised a 400 for
# anything it could not read. Parsing now happens after the response, so
# there is no request left to raise into: a file that cannot be read is
# written to the processing log instead.
#
# tests/test_upload_does_not_block.py covers the split -- what still
# refuses immediately, and what is recorded rather than raised.



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

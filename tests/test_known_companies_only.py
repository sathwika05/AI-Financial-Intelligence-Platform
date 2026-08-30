"""
Only companies this corpus covers can be fetched.

The corpus is fifty companies, seeded from seeds/companies.csv. Fetching
filings for anything else produces documents that resolve to no company,
cannot be filtered by one, and answer questions about a company the
benchmark has no metrics for.

Enforced on the server, not only in the dropdown: the dropdown is a
convenience and anyone can post around it.
"""
import pytest


KNOWN = {"AAPL", "MSFT", "NVDA"}


class TestTheGuard:
    def test_a_known_ticker_passes(self):
        from backend.api.ingestion_routes import _require_known_ticker

        assert _require_known_ticker("AAPL", KNOWN) == "AAPL"

    def test_it_is_case_insensitive(self):
        from backend.api.ingestion_routes import _require_known_ticker

        assert _require_known_ticker(" aapl ", KNOWN) == "AAPL"

    def test_an_unknown_ticker_is_refused(self):
        from fastapi import HTTPException

        from backend.api.ingestion_routes import _require_known_ticker

        with pytest.raises(HTTPException) as caught:
            _require_known_ticker("TSLA", KNOWN)

        assert caught.value.status_code == 400

    def test_the_refusal_names_the_company_and_the_source_of_the_list(self):
        """
        "Not allowed" is useless. Whoever hit this needs to know the list
        exists and where it comes from.
        """
        from fastapi import HTTPException

        from backend.api.ingestion_routes import _require_known_ticker

        with pytest.raises(HTTPException) as caught:
            _require_known_ticker("TSLA", KNOWN)

        detail = caught.value.detail

        assert "TSLA" in detail
        assert "companies.csv" in detail

    def test_an_empty_ticker_is_refused(self):
        from fastapi import HTTPException

        from backend.api.ingestion_routes import _require_known_ticker

        with pytest.raises(HTTPException):
            _require_known_ticker("", KNOWN)


class TestTheCompanyList:
    def test_the_endpoint_is_mounted_and_admin_only(self):
        from backend.auth.roles import Role
        from backend.main import build_app

        app = build_app(deployment_mode="full")

        routes = [
            r for r in app.routes
            if getattr(r, "path", "") == "/api/ingestion/companies"
        ]

        assert routes, "the companies route is not mounted"

        for route in routes:
            required = [
                getattr(d.call, "__required_role__", None)
                for d in route.dependant.dependencies
            ]
            assert Role.ADMIN in required


class TestTheCorpusMatchesItsSeed:
    @pytest.mark.asyncio
    async def test_every_company_in_the_table_is_in_the_csv(self):
        """
        The dropdown is served from the table because that is what
        company_id resolves against. This is the check that the table has
        not drifted from the file it was seeded from -- if it has, the
        dropdown offers a company the seed would not recreate.
        """
        import csv
        from pathlib import Path

        from sqlalchemy import text

        from backend.services.postgres_service import engine

        root = Path(__file__).resolve().parents[1]

        with open(root / "seeds" / "companies.csv") as handle:
            from_csv = {
                row["ticker"].strip().upper()
                for row in csv.DictReader(handle)
                if row.get("ticker")
            }

        async with engine.connect() as connection:
            result = await connection.execute(text("SELECT ticker FROM companies"))
            from_db = {row[0].strip().upper() for row in result}

        assert from_db == from_csv

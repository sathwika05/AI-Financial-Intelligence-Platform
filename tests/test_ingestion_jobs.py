"""
The two long-running jobs the admin screen can start.

They are not alike, and the tests are shaped by the difference.

Collecting EDGAR filings adds to the corpus: a duplicate is skipped, a
failure loses nothing, and running it twice is a no-op. It needs no
guarding beyond the admin role.

Reseeding TRUNCATEs documents, document_chunks, financial_metrics and
companies, then refetches live data that will not match what was there.
It destroys the benchmark corpus and the ground truth derived from it. A
button cannot be allowed to do that on one click, so the endpoint refuses
without a typed confirmation.
"""
import pytest

from backend.auth.roles import Role


class TestBothAreGuarded:
    def test_the_job_routes_are_admin_only(self):
        from backend.main import build_app

        app = build_app(deployment_mode="full")

        paths = {"/api/ingestion/edgar/collect", "/api/ingestion/seed"}
        found = [r for r in app.routes if getattr(r, "path", "") in paths]

        assert {r.path for r in found} == paths, "a job route is not mounted"

        for route in found:
            required = [
                getattr(d.call, "__required_role__", None)
                for d in route.dependant.dependencies
            ]
            assert Role.ADMIN in required, f"{route.path} is not admin-only"

    def test_neither_exists_on_the_public_deployment(self):
        from backend.main import build_app

        paths = {
            getattr(r, "path", "")
            for r in build_app(deployment_mode="portfolio").routes
        }

        assert "/api/ingestion/seed" not in paths
        assert "/api/ingestion/edgar/collect" not in paths


class TestTheReseedConfirmation:
    def test_the_exact_phrase_is_required(self):
        from backend.api.ingestion_routes import RESEED_CONFIRMATION, _require_confirmation

        # Does not raise.
        _require_confirmation(RESEED_CONFIRMATION)

    def test_an_empty_confirmation_is_refused(self):
        from fastapi import HTTPException

        from backend.api.ingestion_routes import _require_confirmation

        with pytest.raises(HTTPException) as caught:
            _require_confirmation("")

        assert caught.value.status_code == 400

    def test_a_near_miss_is_refused(self):
        """
        Typing it is the point. Accepting anything close would make the
        confirmation a formality rather than a decision.
        """
        from fastapi import HTTPException

        from backend.api.ingestion_routes import _require_confirmation

        for attempt in ("yes", "confirm", "replace corpus", "Replace The Corpus"):
            with pytest.raises(HTTPException):
                _require_confirmation(attempt)

    def test_the_refusal_says_what_would_be_destroyed(self):
        """
        Whoever hits this should learn what they were about to do.
        """
        from fastapi import HTTPException

        from backend.api.ingestion_routes import _require_confirmation

        with pytest.raises(HTTPException) as caught:
            _require_confirmation("")

        detail = caught.value.detail.lower()

        assert "documents" in detail
        assert "companies" in detail


class TestCollectingInBulk:
    @pytest.mark.asyncio
    async def test_every_ticker_is_collected(self):
        from backend.api.ingestion_routes import _collect_many

        collected = []

        async def index_one(ticker, **_kwargs):
            collected.append(ticker)
            return 2

        summary = await _collect_many(
            ["AAPL", "MSFT"], forms=("10-K",), limit=2, index_one=index_one
        )

        assert collected == ["AAPL", "MSFT"]
        assert summary["indexed"] == 4

    @pytest.mark.asyncio
    async def test_one_bad_ticker_does_not_stop_the_run(self):
        """
        Twenty tickers and one typo should leave nineteen collected, and
        say which one failed.
        """
        from backend.api.ingestion_routes import _collect_many

        async def index_one(ticker, **_kwargs):
            if ticker == "NOPE":
                raise RuntimeError("no such company")
            return 1

        summary = await _collect_many(
            ["AAPL", "NOPE", "MSFT"], forms=("10-K",), limit=1, index_one=index_one
        )

        assert summary["indexed"] == 2
        assert summary["failed"] == ["NOPE"]

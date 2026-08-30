"""
Only forms EDGAR actually publishes can be asked for.

A bad form is the quietest mistake on the screen. Nothing rejects it:
recent_filings simply matches nothing, the run reports success having
done nothing, and the only trace is a log line on the server. Someone
typing 10-X, or asking a company for a form it never files, sees the same
"collecting" message as someone whose run worked.
"""
import pytest


class TestTheGuard:
    def test_a_known_form_passes(self):
        from backend.api.ingestion_routes import _require_known_forms

        assert _require_known_forms(["10-K", "10-Q"]) == ("10-K", "10-Q")

    def test_it_is_case_and_space_insensitive(self):
        from backend.api.ingestion_routes import _require_known_forms

        assert _require_known_forms([" 10-k ", "10-Q"]) == ("10-K", "10-Q")

    def test_an_invented_form_is_refused(self):
        from fastapi import HTTPException

        from backend.api.ingestion_routes import _require_known_forms

        with pytest.raises(HTTPException) as caught:
            _require_known_forms(["10-X"])

        assert caught.value.status_code == 400
        assert "10-X" in caught.value.detail

    def test_the_refusal_lists_what_is_available(self):
        """
        A rejected form is only useful if it says which ones exist.
        """
        from fastapi import HTTPException

        from backend.api.ingestion_routes import SUPPORTED_FORMS, _require_known_forms

        with pytest.raises(HTTPException) as caught:
            _require_known_forms(["ANNUAL REPORT"])

        for form in SUPPORTED_FORMS:
            assert form in caught.value.detail

    def test_asking_for_no_forms_is_refused(self):
        from fastapi import HTTPException

        from backend.api.ingestion_routes import _require_known_forms

        with pytest.raises(HTTPException):
            _require_known_forms([])

        with pytest.raises(HTTPException):
            _require_known_forms(["", "  "])


class TestARunThatFindsNothingSaysSo:
    @pytest.mark.asyncio
    async def test_the_summary_reports_zero(self):
        """
        The run itself has to carry the count, or "it worked" and "it
        found nothing" are the same outcome.
        """
        from backend.api.ingestion_routes import _collect_many

        async def index_none(_ticker, **_kwargs):
            return 0

        summary = await _collect_many(
            ["AAPL"], forms=("10-K",), limit=1, index_one=index_none
        )

        assert summary["indexed"] == 0
        assert summary["failed"] == []

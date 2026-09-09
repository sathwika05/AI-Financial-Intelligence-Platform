"""
"What is your p95?" needs a row per query, not a log line.

retrieval_logs has been in the schema since the beginning with no
writer, so the answer to every operational question about live traffic
was "I don't have it". system_logs holds text a person reads; no amount
of grep over prose produces a percentile.

WHAT IS RECORDED
    One row per query that reached the pipeline: the masked question, the
    intent that decided its route, how long it took, and how it ended.

WHAT IS NOT
    The raw question. Portfolio mode is public and unauthenticated, so
    what people type is not assumed to be safe to keep. It gets the same
    treatment security events already give it -- PII-masked, truncated.

IT MUST NOT BREAK A QUERY
    This is a diagnostic on the live path. A database that will not take
    the row must not turn a completed pipeline run into a 500, so every
    failure is swallowed and logged, following security/events.py.
"""
from __future__ import annotations

import pytest

from backend.observability import query_log


class TestWhatGoesInTheRow:
    def test_the_intent_is_the_route(self):
        row = query_log.build_row(
            query="undervalued healthcare companies",
            final_report={"intent": "VALUATION", "review": {}},
            latency_ms=41200.0,
        )

        assert row["retrieval_path"] == "VALUATION"

    def test_the_decision_is_carried(self):
        row = query_log.build_row(
            query="q",
            final_report={
                "intent": "SENTIMENT",
                "review": {"decision": "withheld_provider_unavailable"},
            },
            latency_ms=1.0,
        )

        assert row["decision"] == "withheld_provider_unavailable"

    def test_latency_is_carried(self):
        row = query_log.build_row(
            query="q", final_report={}, latency_ms=1234.5
        )

        assert row["latency_ms"] == 1234.5

    def test_a_refused_question_still_records(self):
        """
        Out-of-scope queries are the cheap population, and knowing how
        many of them there are is the point of separating them.
        """
        row = query_log.build_row(
            query="hello",
            final_report={
                "intent": "OUT_OF_SCOPE",
                "review": {"decision": "OUT_OF_SCOPE"},
            },
            latency_ms=980.0,
        )

        assert row["retrieval_path"] == "OUT_OF_SCOPE"
        assert row["decision"] == "OUT_OF_SCOPE"


class TestTheQuestionIsNotKeptRaw:
    def test_an_email_is_masked(self):
        row = query_log.build_row(
            query="what about sathwika@example.com holdings",
            final_report={},
            latency_ms=1.0,
        )

        assert "sathwika@example.com" not in row["query"]

    def test_it_is_truncated(self):
        row = query_log.build_row(
            query="x" * 5000, final_report={}, latency_ms=1.0
        )

        assert len(row["query"]) <= query_log.MAX_STORED_QUERY

    def test_ordinary_questions_survive_intact(self):
        """
        Masking that mangles normal finance wording would make the table
        useless for finding out what people actually ask.
        """
        question = "Which healthcare companies have the strongest revenue growth?"

        row = query_log.build_row(
            query=question, final_report={}, latency_ms=1.0
        )

        assert row["query"] == question


class TestMissingPiecesDoNotStopIt:
    @pytest.mark.parametrize("report", [None, {}, {"review": None}])
    def test_an_absent_report_still_records_the_timing(self, report):
        """
        A query that failed before the reviewer ran is exactly the kind
        worth counting.
        """
        row = query_log.build_row(
            query="q", final_report=report, latency_ms=99.0
        )

        assert row["latency_ms"] == 99.0
        assert row["decision"] is None

    def test_an_unknown_intent_is_recorded_as_unknown(self):
        row = query_log.build_row(
            query="q", final_report={"review": {}}, latency_ms=1.0
        )

        assert row["retrieval_path"] == "unknown"


class TestItNeverRaises:
    async def test_a_broken_database_does_not_reach_the_caller(
        self, monkeypatch
    ):
        async def explode(**kwargs):
            raise RuntimeError("connection refused")

        monkeypatch.setattr(query_log, "_insert", explode)

        # No exception, and nothing returned that a caller must check.
        assert await query_log.record(
            query="q", final_report={}, latency_ms=1.0
        ) is None

    async def test_a_malformed_report_does_not_reach_the_caller(
        self, monkeypatch
    ):
        recorded = {}

        async def capture(**kwargs):
            recorded.update(kwargs)

        monkeypatch.setattr(query_log, "_insert", capture)

        assert await query_log.record(
            query="q",
            final_report="not a dict at all",
            latency_ms=1.0,
        ) is None


class TestTheRouteWritesIt:
    def test_the_query_route_records(self):
        import inspect

        from backend.api import financial_routes

        source = inspect.getsource(financial_routes)

        assert "query_log.record(" in source

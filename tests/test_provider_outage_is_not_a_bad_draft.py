"""
Running out of provider budget is not a failure of the analysis.

The demo runs on a Groq free tier whose ceiling is 200,000 tokens per
day for the whole organisation:

    429 -- tokens per day (TPD): Limit 200000, Used 199833, Requested 451

When that is reached, the analysis node's LARGE-tier call raises, the
broad `except Exception` returns _empty_report, and the reviewer's
empty-draft branch withholds with:

    decision: withheld_empty_draft
    "The analysis produced no draft report."

Which reads as "this system is broken". The truth is "this demo has
spent its allowance for today", and the difference matters to the only
people who will ever see it -- a tester, on their second question.

Same shape as the reviewer fix: a transport failure was being reported
as a content failure. The provider call moves behind its own seam, so
anything it raises is a fact about the provider rather than about the
draft, and the report says which.
"""
from __future__ import annotations

import json

import pytest

from backend.nodes import analysis_node
from backend.nodes.analysis_node import _empty_report


class OutOfBudget(Exception):
    """Stands in for a 429; the exception type must not matter."""


def _ranked(n: int = 2) -> list[dict]:
    return [
        {
            "ticker": f"T{i}",
            "name": f"Company {i}",
            "metrics": {"pe_ratio": 20, "revenue_growth": 0.1},
            "evidence": [{"citation_id": f"c{i}", "source": "vector",
                          "text": "x", "supports": "y"}],
        }
        for i in range(n)
    ]


class TestTheEmptyReportSaysWhichKindOfEmpty:
    def test_by_default_it_is_not_a_provider_outage(self):
        report = _empty_report(
            query="q", intent="GROWTH", reason="No companies ranked"
        )

        assert report.get("provider_unavailable") is False

    def test_it_can_be_marked_as_one(self):
        report = _empty_report(
            query="q",
            intent="GROWTH",
            reason="provider refused",
            provider_unavailable=True,
        )

        assert report["provider_unavailable"] is True

    def test_the_shape_is_otherwise_unchanged(self):
        """
        Everything downstream reads companies and report_flags.
        """
        report = _empty_report(query="q", intent="GROWTH", reason="r")

        assert report["companies"] == []
        assert report["overall_confidence"] == 0.0
        assert report["report_flags"] == ["r"]


class TestAProviderFailureIsMarked:
    async def test_a_raised_provider_call_marks_the_report(
        self, monkeypatch
    ):
        async def refuse(*args, **kwargs):
            raise OutOfBudget("429 tokens per day")

        monkeypatch.setattr(
            analysis_node, "_call_analysis_model", refuse
        )

        report = await analysis_node.run_llm_analysis(
            query="Which healthcare companies grew fastest?",
            intent="GROWTH",
            ranked=_ranked(),
            config={},
        )

        assert report["companies"] == []
        assert report["provider_unavailable"] is True

    async def test_malformed_json_is_not_a_provider_outage(
        self, monkeypatch
    ):
        """
        The model answered. It answered badly. That is a content
        failure and must keep saying so.
        """
        async def garbage(*args, **kwargs):
            return "not json at all"

        monkeypatch.setattr(
            analysis_node, "_call_analysis_model", garbage
        )

        report = await analysis_node.run_llm_analysis(
            query="q", intent="GROWTH", ranked=_ranked(), config={}
        )

        assert report["companies"] == []
        assert report["provider_unavailable"] is False

    async def test_no_ranked_companies_is_not_a_provider_outage(self):
        report = await analysis_node.run_llm_analysis(
            query="q", intent="GROWTH", ranked=[], config={}
        )

        assert report["provider_unavailable"] is False

    async def test_a_good_report_is_untouched(self, monkeypatch):
        async def good(*args, **kwargs):
            return json.dumps({
                "query_summary": "q",
                "overall_confidence": 0.8,
                "companies": [{"ticker": "T0", "name": "Company 0"}],
            })

        monkeypatch.setattr(
            analysis_node, "_call_analysis_model", good
        )

        report = await analysis_node.run_llm_analysis(
            query="q", intent="GROWTH", ranked=_ranked(), config={}
        )

        assert len(report["companies"]) == 1
        assert not report.get("provider_unavailable")


class TestTheReaderIsToldTheRealReason:
    @staticmethod
    async def _withheld(draft: dict) -> dict:
        from backend.nodes.reviewer_node import reviewer_node

        result = await reviewer_node({"draft_report": draft}, config={})
        return result["final_report"] or {}

    async def test_a_provider_outage_has_its_own_decision(self):
        report = await self._withheld(
            {"companies": [], "provider_unavailable": True}
        )

        assert report["review"]["decision"] == "withheld_provider_unavailable"

    async def test_the_notice_does_not_blame_the_draft(self):
        report = await self._withheld(
            {"companies": [], "provider_unavailable": True}
        )

        notice = report["review"]["notice"].lower()

        assert "no draft" not in notice
        assert any(
            word in notice for word in ("capacity", "limit", "allowance")
        ), "the reader should learn this is a quota, not a fault"

    async def test_an_ordinary_empty_draft_is_unchanged(self):
        report = await self._withheld({"companies": []})

        assert report["review"]["decision"] == "withheld_empty_draft"
        assert report["withheld"] is True

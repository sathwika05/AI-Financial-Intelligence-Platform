"""
A rate limit is not a hallucination.

`_llm_hallucination_check` caught every exception and returned
`hallucination_rate: 1.0` with the comment "Fail safely instead of
silently approving". The instinct is right and the granularity is wrong:
it makes "the model judged these claims unsupported" and "I could not
reach the model" produce the same number, and only the first of those is
a fact about the draft.

Observed live on the free Groq tier, running one SENTIMENT query:

    groq.RateLimitError: 429 -- tokens per minute (TPM):
    Limit 8000, Used 5638, Requested 3618
    [REVIEWER] LLM hallucination check failed
    [REVIEWER] Retry triggered hallucination_rate=1.00 flags=14

1.0 is above HALLUCINATION_THRESHOLD, so it sets quality_failure, so the
graph retries -- regenerating the draft on the LARGE tier and running the
reviewer again, which requests more tokens against the limit that just
rejected it. The failure feeds itself:

    429 -> rate 1.0 -> retry -> more tokens -> 429 -> ...

until MAX_RETRIES, and then a withheld report blaming the draft for an
infrastructure failure.

THE FIX IS NOT TO APPROVE
    An unreviewed draft must still never be presented as reviewed. It
    stops retrying, because retrying is what makes the rate limit worse,
    and it withholds under its own decision so the notice can say what
    actually happened instead of naming a flag count the reviewer never
    produced.
"""
from __future__ import annotations

import pytest

from backend.nodes import reviewer_node
from backend.nodes.reviewer_node import (
    HALLUCINATION_THRESHOLD,
    MAX_RETRIES,
    build_final_output,
    run_reviewer,
)


def _draft(companies: int = 3) -> dict:
    return {
        "query_summary": "What did management say about AI?",
        "intent": "SENTIMENT",
        "overall_confidence": 0.86,
        "evidence_quality": "High",
        "companies": [
            {
                "ticker": f"T{i}",
                "name": f"Company {i}",
                "summary": "Management discussed AI investment.",
                "evidence": [{"citation_id": f"c{i}", "claim": "AI"}],
            }
            for i in range(companies)
        ],
    }


def _ranked(companies: int = 3) -> list[dict]:
    return [
        {
            "ticker": f"T{i}",
            "evidence": [
                {"citation_id": f"c{i}", "source": "vector",
                 "text": "AI investment", "supports": "AI"}
            ],
        }
        for i in range(companies)
    ]


class RateLimited(Exception):
    """Stands in for groq.RateLimitError; the type must not matter."""


@pytest.fixture
def unreachable_judge(monkeypatch):
    """The judge raises, the way a 429 does."""
    async def boom(*args, **kwargs):
        raise RateLimited("429 tokens per minute")

    monkeypatch.setattr(reviewer_node, "_call_hallucination_judge", boom)


class TestTheCheckReportsThatItCouldNotRun:
    async def test_it_does_not_claim_total_hallucination(
        self, unreachable_judge
    ):
        result = await reviewer_node._llm_hallucination_check(
            draft_report=_draft(),
            ranked_companies=_ranked(),
            config={},
        )

        assert result["hallucination_rate"] == 0.0, (
            "an unreachable judge produced no verdict; 1.0 is a verdict"
        )

    async def test_it_says_so_explicitly(self, unreachable_judge):
        result = await reviewer_node._llm_hallucination_check(
            draft_report=_draft(),
            ranked_companies=_ranked(),
            config={},
        )

        assert result["check_unavailable"] is True

    async def test_a_real_verdict_is_not_marked_unavailable(
        self, monkeypatch
    ):
        async def judged(*args, **kwargs):
            return '{"hallucination_rate": 0.8, "flagged_claims": ["x"]}'

        monkeypatch.setattr(
            reviewer_node, "_call_hallucination_judge", judged
        )

        result = await reviewer_node._llm_hallucination_check(
            draft_report=_draft(),
            ranked_companies=_ranked(),
            config={},
        )

        assert result["hallucination_rate"] == 0.8
        assert result.get("check_unavailable") is False


class TestItStopsTheRetryStorm:
    async def test_it_does_not_retry(self, unreachable_judge):
        result = await run_reviewer(
            draft_report=_draft(),
            ranked_companies=_ranked(),
            retry_count=0,
            config={},
        )

        assert result["should_retry"] is False, (
            "retrying is what makes a rate limit worse"
        )

    async def test_it_does_not_pass(self, unreachable_judge):
        result = await run_reviewer(
            draft_report=_draft(),
            ranked_companies=_ranked(),
            retry_count=0,
            config={},
        )

        assert result["passed"] is False

    async def test_it_has_its_own_decision(self, unreachable_judge):
        result = await run_reviewer(
            draft_report=_draft(),
            ranked_companies=_ranked(),
            retry_count=0,
            config={},
        )

        assert result["decision"] == "withheld_review_unavailable"

    async def test_the_rate_is_not_inflated(self, unreachable_judge):
        result = await run_reviewer(
            draft_report=_draft(),
            ranked_companies=_ranked(),
            retry_count=0,
            config={},
        )

        assert result["hallucination_rate"] == 0.0
        assert result["hallucination_rate"] <= HALLUCINATION_THRESHOLD


class TestARealHallucinationStillRetries:
    """
    The guard must not become a way to skip review.
    """

    @pytest.fixture
    def hallucinating_judge(self, monkeypatch):
        async def judged(*args, **kwargs):
            return '{"hallucination_rate": 0.9, "flagged_claims": ["a","b"]}'

        monkeypatch.setattr(
            reviewer_node, "_call_hallucination_judge", judged
        )

    async def test_it_retries(self, hallucinating_judge):
        result = await run_reviewer(
            draft_report=_draft(),
            ranked_companies=_ranked(),
            retry_count=0,
            config={},
        )

        assert result["should_retry"] is True
        assert result["decision"] == "retry"

    async def test_it_still_forces_a_terminal_at_the_limit(
        self, hallucinating_judge
    ):
        result = await run_reviewer(
            draft_report=_draft(),
            ranked_companies=_ranked(),
            retry_count=MAX_RETRIES,
            config={},
        )

        assert result["should_retry"] is False
        assert result["decision"] == "forced_pass"


class TestWhatTheReaderIsTold:
    def test_the_ranking_is_withheld(self):
        output = build_final_output(
            draft_report=_draft(),
            review_result={
                "decision": "withheld_review_unavailable",
                "passed": False,
                "should_retry": False,
                "confidence_flags": [],
                "evidence_flags": [],
                "hallucination_flags": [],
                "company_flags": [],
                "citation_flags": [],
                "hallucination_rate": 0.0,
                "total_flags": 0,
                "actionable_flag_count": 0,
            },
        )

        assert output["withheld"] is True
        assert output["top_companies"] == []

    def test_the_notice_blames_the_check_not_the_draft(self):
        output = build_final_output(
            draft_report=_draft(),
            review_result={
                "decision": "withheld_review_unavailable",
                "passed": False,
                "should_retry": False,
                "confidence_flags": [],
                "evidence_flags": [],
                "hallucination_flags": [],
                "company_flags": [],
                "citation_flags": [],
                "hallucination_rate": 0.0,
                "total_flags": 0,
                "actionable_flag_count": 0,
            },
        )

        notice = output["review"]["notice"].lower()

        assert notice
        assert "0 unresolved" not in notice, (
            "a flag count the reviewer never produced is not an explanation"
        )
        assert any(
            word in notice for word in ("check", "verif", "review could")
        ), "the reader should be told the verification did not run"

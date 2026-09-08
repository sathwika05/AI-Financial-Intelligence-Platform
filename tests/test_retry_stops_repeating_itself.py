"""
A retry that sends the same feedback twice cannot converge.

Observed live, one SENTIMENT query:

    retry_count=0  hallucination_rate=0.00  flags=13
    retry_count=1  hallucination_rate=0.00  flags=13
    retry_count=2  hallucination_rate=0.00  flags=13

Three full analysis passes on the LARGE tier, producing the identical
thirteen flags, because nothing anywhere remembered that this exact
feedback had already been sent and had already failed to help.

WHY THE OBVIOUS FIX DOES NOT WORK
    review_feedback cannot itself carry the memory. The analysis node
    clears it after use (analysis_node.py, `"review_feedback": []`) and
    that clear is correct -- a later, unrelated pass must not re-apply
    stale feedback. So by the time the reviewer runs again the field is
    already empty and there is nothing to compare against. The memory
    needs a second field that survives the clear.

WHAT IT COSTS AND SAVES
    Each avoided retry is one LARGE-tier analysis plus one LARGE-tier
    review, roughly 25 seconds and several thousand tokens. On a free
    tier capped at 200,000 tokens per day for the whole organisation,
    that is the difference between a demo that answers ten questions and
    one that answers thirty.

DELIBERATELY NARROW
    Only an identical repeat stops the loop. Feedback that changed --
    even by one flag -- means the rewrite moved something, and the next
    attempt is allowed to run.
"""
from __future__ import annotations

import pytest

from backend.nodes import reviewer_node
from backend.nodes.reviewer_node import MAX_RETRIES, run_reviewer


def _draft(confidence: float = 0.86) -> dict:
    return {
        "query_summary": "q",
        "intent": "SENTIMENT",
        "overall_confidence": confidence,
        "evidence_quality": "High",
        "companies": [
            {"ticker": "T0", "name": "C0", "summary": "s",
             "evidence": [{"citation_id": "c0", "claim": "x"}]}
        ],
    }


def _ranked() -> list[dict]:
    return [{
        "ticker": "T0",
        "evidence": [{"citation_id": "c0", "source": "vector",
                      "text": "t", "supports": "s"}],
    }]


@pytest.fixture
def flagging_judge(monkeypatch):
    """Always finds the same problem, the way the live run did."""
    async def judged(*args, **kwargs):
        return '{"hallucination_rate": 0.9, "flagged_claims": ["same", "same2"]}'

    monkeypatch.setattr(
        reviewer_node, "_call_hallucination_judge", judged
    )


class TestTheFirstAttemptStillRetries:
    async def test_new_feedback_is_worth_sending(self, flagging_judge):
        result = await run_reviewer(
            draft_report=_draft(),
            ranked_companies=_ranked(),
            retry_count=0,
            config={},
            previous_review_feedback=[],
        )

        assert result["should_retry"] is True
        assert result["decision"] == "retry"

    async def test_it_reports_what_it_sent(self, flagging_judge):
        result = await run_reviewer(
            draft_report=_draft(),
            ranked_companies=_ranked(),
            retry_count=0,
            config={},
            previous_review_feedback=[],
        )

        assert result["review_feedback"] == ["same", "same2"]


class TestAnIdenticalRepeatStops:
    async def test_it_does_not_retry(self, flagging_judge):
        result = await run_reviewer(
            draft_report=_draft(),
            ranked_companies=_ranked(),
            retry_count=1,
            config={},
            previous_review_feedback=["same", "same2"],
        )

        assert result["should_retry"] is False, (
            "the same feedback produced the same draft; again will too"
        )

    async def test_order_does_not_make_it_look_new(self, flagging_judge):
        result = await run_reviewer(
            draft_report=_draft(),
            ranked_companies=_ranked(),
            retry_count=1,
            config={},
            previous_review_feedback=["same2", "same"],
        )

        assert result["should_retry"] is False

    async def test_it_reaches_a_terminal_rather_than_hanging(
        self, flagging_judge
    ):
        result = await run_reviewer(
            draft_report=_draft(),
            ranked_companies=_ranked(),
            retry_count=1,
            config={},
            previous_review_feedback=["same", "same2"],
        )

        assert result["decision"] in {
            "forced_pass", "approved", "withheld_review_unavailable"
        }
        assert result["passed"] is not None


class TestChangedFeedbackIsAllowedToRun:
    async def test_one_different_flag_is_still_progress(
        self, flagging_judge
    ):
        result = await run_reviewer(
            draft_report=_draft(),
            ranked_companies=_ranked(),
            retry_count=1,
            config={},
            previous_review_feedback=["same", "different"],
        )

        assert result["should_retry"] is True

    async def test_a_shorter_previous_list_is_not_a_repeat(
        self, flagging_judge
    ):
        result = await run_reviewer(
            draft_report=_draft(),
            ranked_companies=_ranked(),
            retry_count=1,
            config={},
            previous_review_feedback=["same"],
        )

        assert result["should_retry"] is True


class TestTheRetryLimitStillApplies:
    async def test_new_feedback_still_stops_at_the_limit(
        self, flagging_judge
    ):
        result = await run_reviewer(
            draft_report=_draft(),
            ranked_companies=_ranked(),
            retry_count=MAX_RETRIES,
            config={},
            previous_review_feedback=["something", "else"],
        )

        assert result["should_retry"] is False
        assert result["decision"] == "forced_pass"


class TestTheNodeCarriesTheMemoryAcrossTheClear:
    """
    analysis_node resets review_feedback to []. The guard therefore
    cannot read it, and needs a field the analysis node does not touch.
    """

    def test_analysis_still_clears_the_working_field(self):
        import inspect

        from backend.nodes import analysis_node

        source = inspect.getsource(analysis_node)

        assert '"review_feedback": []' in source, (
            "clearing is correct; the guard must not depend on it stopping"
        )

    def test_analysis_does_not_clear_the_memory(self):
        import inspect

        from backend.nodes import analysis_node

        source = inspect.getsource(analysis_node)

        assert '"previous_review_feedback": []' not in source

    def test_the_state_declares_it(self):
        from backend.state.financial_state import FinancialState

        assert "previous_review_feedback" in FinancialState.__annotations__

    def test_the_reviewer_node_writes_it(self):
        import inspect

        source = inspect.getsource(reviewer_node)

        assert '"previous_review_feedback"' in source

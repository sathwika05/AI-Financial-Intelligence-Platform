"""
A report the reviewer could not clear must not be presented as reviewed.

Two paths returned `passed: True` with `decision: "forced_pass"`.

    1. Retry exhaustion. A live query for "hello" raised fourteen flags,
       four times running, and was then force-passed and rendered with a
       "Reviewed" badge and 52% confidence.

    2. An empty draft. reviewer_node returns early with passed True before
       build_final_output runs, so decide_escalation never executes and an
       empty report cannot be withheld at all.

Escalation already exists and already withholds — below
ESCALATION_THRESHOLD the ranking is absent from the response rather than
hidden by the console. It just cannot fire here: the self-reported
confidence floors around 0.49 on the weakest evidence in the corpus, so
the 0.30 branch has never triggered in practice.

So the fix is not a new mechanism. It is a second reason to reach the one
that exists: the reviewer stopped without resolving its own flags. That is
deliberately additive. decide_escalation keeps its exact meaning and its
tests — the "quiet case" it was written for, a draft with no flags and low
confidence, still escalates on confidence alone.

Separately, the flags that trigger a retry were not the flags forwarded to
the next attempt. Only hallucination flags were carried, and the "hello"
run had a hallucination rate of 0.00 with fourteen flags of other kinds —
so analysis re-ran three times on an identical prompt. Confidence went
0.56, 0.56, 0.52, 0.52, which is sampling noise at temperature zero, not
convergence.
"""
from __future__ import annotations

import pytest

from backend.nodes.reviewer_node import (
    ESCALATION_THRESHOLD,
    actionable_feedback,
    build_final_output,
    decide_escalation,
)


def _draft(confidence: float = 0.86, companies: int = 3) -> dict:
    return {
        "query_summary": "Compare financial services companies",
        "intent": "VALUATION",
        "overall_confidence": confidence,
        "evidence_quality": "High",
        "companies": [
            {"ticker": f"T{i}", "name": f"Company {i}"}
            for i in range(companies)
        ],
    }


def _review(decision: str, flags: int = 0) -> dict:
    return {
        "passed": decision != "retry",
        "should_retry": False,
        "decision": decision,
        "confidence_flags": [],
        "evidence_flags": [f"missing evidence {i}" for i in range(flags)],
        "hallucination_flags": [],
        "company_flags": [],
        "citation_flags": [],
        "hallucination_rate": 0.0,
        "total_flags": flags,
    }


class TestAForcedPassIsWithheld:
    def test_unresolved_flags_withhold_the_ranking(self):
        """
        The failing case: 14 flags, retries exhausted, high confidence.
        Confidence alone would approve this — it is well above 0.30.
        """
        output = build_final_output(
            draft_report=_draft(confidence=0.86),
            review_result=_review("forced_pass", flags=14),
        )

        assert output["withheld"] is True
        assert output["top_companies"] == []

    def test_the_reader_is_told_why(self):
        output = build_final_output(
            draft_report=_draft(confidence=0.86),
            review_result=_review("forced_pass", flags=14),
        )

        notice = output["review"]["notice"]

        assert notice, "a withheld ranking must say why"
        assert "14" in notice, (
            "the count is the reason; a bare apology is not a notice"
        )

    def test_an_approved_report_is_untouched(self):
        """
        The guard is on the forced pass, not on every terminal.
        """
        output = build_final_output(
            draft_report=_draft(confidence=0.86),
            review_result=_review("approved"),
        )

        assert output["withheld"] is False
        assert len(output["top_companies"]) == 3
        assert output["review"]["notice"] is None


class TestConfidenceEscalationIsUnchanged:
    """
    The addition must not disturb the quiet case decide_escalation exists
    for: no flags, low confidence, no retries.
    """

    def test_low_confidence_still_escalates_on_its_own(self):
        assert decide_escalation(
            overall_confidence=0.18,
            should_retry=False,
        ) is True

    def test_the_boundary_is_still_strict(self):
        assert decide_escalation(
            overall_confidence=ESCALATION_THRESHOLD,
            should_retry=False,
        ) is False

    def test_a_quiet_low_confidence_approval_is_withheld(self):
        output = build_final_output(
            draft_report=_draft(confidence=0.18),
            review_result=_review("approved"),
        )

        assert output["withheld"] is True
        assert output["top_companies"] == []


class TestAnEmptyDraftIsNotAPass:
    @pytest.mark.parametrize(
        "draft",
        [{}, {"companies": []}],
        ids=["no draft", "no companies"],
    )
    async def test_it_is_withheld_rather_than_passed(self, draft):
        from backend.nodes.reviewer_node import reviewer_node

        result = await reviewer_node({"draft_report": draft}, config={})

        report = result["final_report"] or {}

        assert result["review_result"]["passed"] is False, (
            "an empty draft was returning passed=True and a Reviewed badge"
        )
        assert report.get("withheld") is True
        assert report.get("top_companies", []) == []


class TestEveryTriggeringFlagIsForwarded:
    """
    The three predicates that set quality_failure are a hallucination rate
    above threshold, any evidence flag, and any citation flag. Forwarding
    only hallucination flags meant two of the three triggers produced an
    empty feedback list, so the retry could not converge by construction.
    """

    def test_evidence_flags_reach_the_next_attempt(self):
        feedback = actionable_feedback(
            _review("retry", flags=0) | {"evidence_flags": ["a", "b"]}
        )

        assert feedback == ["a", "b"]

    def test_citation_and_company_flags_are_carried(self):
        feedback = actionable_feedback(
            _review("retry")
            | {
                "citation_flags": ["bad citation"],
                "company_flags": ["wrong company"],
            }
        )

        assert "bad citation" in feedback
        assert "wrong company" in feedback

    def test_hallucination_flags_are_still_carried(self):
        feedback = actionable_feedback(
            _review("retry") | {"hallucination_flags": ["unsupported"]}
        )

        assert feedback == ["unsupported"]

    def test_confidence_flags_are_not(self):
        """
        "Confidence is low" is not something a rewrite can act on. Sending
        it back would spend an attempt restating the problem.
        """
        feedback = actionable_feedback(
            _review("retry") | {"confidence_flags": ["low confidence"]}
        )

        assert feedback == []

    def test_a_triggering_review_always_has_something_to_send(self):
        """
        The property that makes an empty-feedback retry unreachable: every
        predicate that can set quality_failure also populates a list that
        actionable_feedback forwards.
        """
        for trigger in ("evidence_flags", "citation_flags", "hallucination_flags"):
            review = _review("retry") | {trigger: ["flagged"]}

            assert actionable_feedback(review), (
                f"{trigger} triggers a retry but forwards nothing"
            )


class TestMetricsAreEvidenceWhenTheQuestionIsAboutNumbers:
    """
    "healthcare companies with the strongest revenue growth" was withheld
    with 21 flags, five of them "no retrieval evidence — backed only by
    database metrics". Revenue growth is a column; there is no filing to
    cite for it. Demanding a document chunk for a database fact set
    has_missing_evidence, forced three retries, and — once the forced pass
    became a withhold — turned every metrics-only question into a refusal,
    including two of the four questions the console offers as examples.

    Same mistake the retrieval-precision metric made: judging a structured
    result by document-retrieval criteria.
    """

    @staticmethod
    def _metrics_only(ticker: str = "JNJ") -> list[dict]:
        return [
            {
                "ticker": ticker,
                "evidence": [
                    {
                        "citation_id": f"{ticker}-metrics-1",
                        "source": "metrics",
                        "text": f"{ticker}: revenue growth=12.7%.",
                        "supports": "valuation/growth metrics",
                    }
                ],
            }
        ]

    @pytest.mark.parametrize("intent", ["GROWTH", "VALUATION", "growth"])
    def test_metrics_only_is_grounded_for_a_numeric_question(self, intent):
        from backend.nodes.reviewer_node import _check_retrieval_evidence

        assert _check_retrieval_evidence(
            self._metrics_only(), intent=intent
        ) == []

    @pytest.mark.parametrize("intent", ["SENTIMENT", "MIXED", None])
    def test_it_is_still_a_failure_when_the_question_is_about_narrative(
        self, intent
    ):
        """
        A claim about what management said needs a document. Unchanged.
        """
        from backend.nodes.reviewer_node import _check_retrieval_evidence

        flags = _check_retrieval_evidence(
            self._metrics_only(), intent=intent
        )

        assert len(flags) == 1
        assert "database metrics" in flags[0]

    @pytest.mark.parametrize("intent", ["GROWTH", "SENTIMENT"])
    def test_no_evidence_at_all_is_a_failure_for_every_intent(self, intent):
        """
        The original comment was right that empty is worse than
        metrics-only. Relaxing metrics-only must not relax empty.
        """
        from backend.nodes.reviewer_node import _check_retrieval_evidence

        flags = _check_retrieval_evidence(
            [{"ticker": "JNJ", "evidence": []}], intent=intent
        )

        assert len(flags) == 1
        assert "no evidence of any kind" in flags[0]

    def test_retrieved_evidence_is_never_flagged(self):
        from backend.nodes.reviewer_node import _check_retrieval_evidence

        assert _check_retrieval_evidence(
            [
                {
                    "ticker": "JNJ",
                    "evidence": [
                        {"source": "metrics"},
                        {"source": "vector"},
                    ],
                }
            ],
            intent="SENTIMENT",
        ) == []


class TestTheReaderIsToldHowManyIssuesMattered:
    def test_confidence_flags_are_not_counted_as_unresolved(self):
        """
        Six of twenty-one flags on the withheld report were "confidence
        0.45 is below threshold 0.70", one per company — derived from a
        self-reported score that never enters the retry decision.
        """
        review = _review("forced_pass", flags=2) | {
            "confidence_flags": ["low", "low", "low"],
            "total_flags": 5,
            "actionable_flag_count": 2,
        }

        output = build_final_output(
            draft_report=_draft(confidence=0.86),
            review_result=review,
        )

        assert "2" in output["review"]["notice"]
        assert "5" not in output["review"]["notice"]

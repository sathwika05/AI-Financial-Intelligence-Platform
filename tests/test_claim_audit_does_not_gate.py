"""
The claim audit must not touch pass/fail or overall_score.

finalize_question_result averages every applicable evaluator's score into
overall_score, and fails the question if any of them reports passed=False.
So an evaluator added to `evaluator_results` is never additive -- it
silently re-scores every question that has already been benchmarked, and
the 82% from an earlier run stops meaning what it meant.

The audit therefore lives in its own field on QuestionEvaluationResult and
its own table. It computes no score, casts no vote, and these tests exist
to keep it that way: they compare a finalized result with the audit
attached against the identical result without it.
"""
from backend.evaluation.aggregation import finalize_question_result
from backend.evaluation.claims.audit import ClaimAudit, ClaimRecord
from backend.evaluation.schemas import (
    EvaluatorResult,
    QuestionEvaluationResult,
)


def _result(with_audit: bool) -> QuestionEvaluationResult:
    """One question, scored identically, differing only in the audit."""
    result = QuestionEvaluationResult(
        question_id="mixed_002",
        question="Rank the five best AI-related stocks.",
        expected_intent="MIXED",
        actual_intent="MIXED",
        evaluator_results={
            "intent": EvaluatorResult(
                evaluator="intent", score=1.0, passed=True
            ),
            "ragas": EvaluatorResult(
                evaluator="ragas", score=0.6465, passed=False
            ),
            "ranking": EvaluatorResult(
                evaluator="ranking", score=0.9873, passed=True
            ),
        },
    )

    if with_audit:
        result.claim_audit = ClaimAudit(
            claims=[
                ClaimRecord(
                    index=0,
                    claim="Revenue grew 12%.",
                    original="Revenue grew 12%.",
                    is_numeric=True,
                    numeric_values=("12%",),
                    evidence=["NVDA revenue rose from $50.0B to $56.0B."],
                    label="UNSUPPORTED",
                    reasoning="The evidence shows 12% but for a different period.",
                    evaluator_model="gpt-4o-mini",
                ),
            ],
            dropped=["NVDA may benefit from AI demand."],
        )

    return result


class TestTheAuditChangesNothing:
    def test_overall_score_is_identical(self):
        """
        The audit's labels are not scores and must never be averaged into
        one. A question scoring 0.8973 keeps scoring 0.8973.
        """
        assert (
            finalize_question_result(_result(True)).overall_score
            == finalize_question_result(_result(False)).overall_score
        )

    def test_passed_is_identical(self):
        assert (
            finalize_question_result(_result(True)).passed
            == finalize_question_result(_result(False)).passed
        )

    def test_a_question_with_only_unsupported_claims_still_passes(self):
        """
        The sharpest version: every claim fabricated, every existing
        evaluator happy. The benchmark's verdict is unchanged, and the
        audit is what tells you something is wrong.
        """
        result = QuestionEvaluationResult(
            question_id="valuation_001",
            question="Which three Technology companies have the lowest P/E?",
            expected_intent="VALUATION",
            evaluator_results={
                "intent": EvaluatorResult(
                    evaluator="intent", score=1.0, passed=True
                ),
                "sql": EvaluatorResult(
                    evaluator="sql", score=1.0, passed=True
                ),
            },
            claim_audit=ClaimAudit(
                claims=[
                    ClaimRecord(
                        index=0,
                        claim="Revenue grew 40%.",
                        original="Revenue grew 40%.",
                        is_numeric=True,
                        numeric_values=("40%",),
                        evidence=["nothing about revenue"],
                        label="UNSUPPORTED",
                        reasoning="Fabricated.",
                        evaluator_model="gpt-4o-mini",
                    ),
                ],
            ),
        )

        finalized = finalize_question_result(result)

        assert finalized.passed is True
        assert finalized.overall_score == 1.0

    def test_the_audit_is_not_in_evaluator_results(self):
        """
        Belt and braces. If it ever appears there, finalize picks it up as
        an applicable evaluator and both guarantees above are gone.
        """
        finalized = finalize_question_result(_result(True))

        assert "claim" not in finalized.evaluator_results
        assert "claims" not in finalized.evaluator_results
        assert "claim_audit" not in finalized.evaluator_results

    def test_the_audit_survives_finalization(self):
        """Not gating is not the same as being thrown away."""
        finalized = finalize_question_result(_result(True))

        assert finalized.claim_audit is not None
        assert len(finalized.claim_audit.claims) == 1

    def test_aggregate_metrics_carry_no_claim_keys(self):
        """
        aggregate_metrics is flattened into the run-level row. A claim key
        appearing there would reach evaluation_metrics and change what an
        existing dashboard reads.
        """
        finalized = finalize_question_result(_result(True))

        assert not [
            key for key in finalized.aggregate_metrics
            if "claim" in key.lower()
        ]


class TestTheAuditSummarisesItself:
    def test_it_counts_its_own_labels(self):
        audit = _result(True).claim_audit

        assert audit.total_claims == 1
        assert audit.unsupported == 1
        assert audit.supported == 0

    def test_dropped_speculation_is_counted_but_not_scored(self):
        """
        Hedges are excluded from the rate and kept on the record, so the
        size of the discard is visible.
        """
        audit = _result(True).claim_audit

        assert audit.dropped_count == 1
        assert audit.total_claims == 1

    def test_an_empty_audit_is_not_a_perfect_score(self):
        """
        An answer that made no checkable claims has no support rate. Zero
        claims must not read as 100% supported anywhere downstream.
        """
        audit = ClaimAudit(claims=[], dropped=[])

        assert audit.total_claims == 0
        assert audit.supported == 0

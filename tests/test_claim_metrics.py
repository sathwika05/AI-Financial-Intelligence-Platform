"""
The two sets of numbers this evaluator produces.

RATES describe the run: of the claims the answers made, how many did the
evidence carry?

AGREEMENT describes the evaluator itself: when a human labelled the same
claims, how often did the judge match? Without it the rates are just
another LLM's opinion, and the whole point of building this was to avoid
adding one of those.

WHY THE POSITIVE CLASS IS "UNSUPPORTED"
    Precision and recall are computed for *detecting unsupported claims*,
    not for overall correctness. In a financial system the expensive
    mistake is a fabricated fact that the evaluator waved through, so
    recall on UNSUPPORTED is the number that matters, and it needs to be
    reported separately rather than buried in an accuracy figure that a
    mostly-supported corpus would keep flatteringly high.

WHY INSUFFICIENT_EVIDENCE IS NOT AN ERROR
    It sits outside the support rate's numerator and inside its
    denominator: the answer made a claim the run could not back, which is
    a retrieval problem rather than a fabrication. Folding it into
    UNSUPPORTED would make an indexing gap look like a hallucination.
"""
import pytest

from backend.evaluation.claims.metrics import (
    agreement_stats,
    claim_rates,
)

# Rates are rounded to four decimals on the way out, matching how the other
# run metrics are stored and displayed. The tolerance here asserts that the
# rounding is correct rather than demanding it not happen.
ROUNDED = 5e-5


def labelled(*pairs):
    """(evaluator_label, human_label) pairs as the DB hands them back."""
    return [
        {"evaluator_label": ev, "human_label": hu}
        for ev, hu in pairs
    ]


class TestRates:
    ROWS = [
        {"evaluator_label": "SUPPORTED"},
        {"evaluator_label": "SUPPORTED"},
        {"evaluator_label": "SUPPORTED"},
        {"evaluator_label": "UNSUPPORTED"},
        {"evaluator_label": "INSUFFICIENT_EVIDENCE"},
    ]

    def test_the_counts_are_reported(self):
        rates = claim_rates(self.ROWS)

        assert rates["total_claims"] == 5
        assert rates["supported"] == 3
        assert rates["unsupported"] == 1
        assert rates["insufficient_evidence"] == 1

    def test_support_rate_is_supported_over_total(self):
        assert claim_rates(self.ROWS)["claim_support_rate"] == 0.6

    def test_unsupported_rate_is_unsupported_over_total(self):
        """
        Not over (supported + unsupported). Excluding the insufficient
        ones would let a run improve its headline number by retrieving
        less.
        """
        assert claim_rates(self.ROWS)["unsupported_fact_rate"] == 0.2

    def test_the_two_rates_do_not_sum_to_one(self):
        """A reminder that the third label is real and is not an error."""
        rates = claim_rates(self.ROWS)

        assert rates["claim_support_rate"] + rates["unsupported_fact_rate"] == 0.8

    def test_no_claims_yields_zeroes_rather_than_dividing_by_zero(self):
        rates = claim_rates([])

        assert rates["total_claims"] == 0
        assert rates["claim_support_rate"] == 0.0
        assert rates["unsupported_fact_rate"] == 0.0


class TestAgreement:
    """
    Six claims, hand-labelled. Two of the judge's UNSUPPORTED calls are
    right, one is a false alarm, and it missed one real fabrication.

        evaluator     human          outcome
        UNSUPPORTED   UNSUPPORTED    true positive
        UNSUPPORTED   UNSUPPORTED    true positive
        UNSUPPORTED   SUPPORTED      false positive
        SUPPORTED     UNSUPPORTED    false negative
        SUPPORTED     SUPPORTED      true negative
        SUPPORTED     SUPPORTED      true negative
    """

    ROWS = labelled(
        ("UNSUPPORTED", "UNSUPPORTED"),
        ("UNSUPPORTED", "UNSUPPORTED"),
        ("UNSUPPORTED", "SUPPORTED"),
        ("SUPPORTED", "UNSUPPORTED"),
        ("SUPPORTED", "SUPPORTED"),
        ("SUPPORTED", "SUPPORTED"),
    )

    def test_only_human_labelled_claims_are_counted(self):
        rows = self.ROWS + [{"evaluator_label": "SUPPORTED", "human_label": None}]

        assert agreement_stats(rows)["validated_claims"] == 6

    def test_agreement_is_exact_label_match(self):
        """Four of six labels match outright."""
        assert agreement_stats(self.ROWS)["agreement"] == pytest.approx(4 / 6, abs=ROUNDED)

    def test_precision_for_detecting_unsupported(self):
        """Of three UNSUPPORTED calls, two were right."""
        assert agreement_stats(self.ROWS)["precision"] == pytest.approx(2 / 3, abs=ROUNDED)

    def test_recall_for_detecting_unsupported(self):
        """Of three real unsupported claims, it caught two."""
        assert agreement_stats(self.ROWS)["recall"] == pytest.approx(2 / 3, abs=ROUNDED)

    def test_f1_is_the_harmonic_mean(self):
        assert agreement_stats(self.ROWS)["f1"] == pytest.approx(2 / 3, abs=ROUNDED)

    def test_false_positives_are_named(self):
        """A false alarm: flagged a claim the human accepted."""
        assert agreement_stats(self.ROWS)["false_positives"] == 1

    def test_false_negatives_are_named(self):
        """
        The expensive one: a fabrication the evaluator let through. This
        is the number to read first.
        """
        assert agreement_stats(self.ROWS)["false_negatives"] == 1

    def test_insufficient_counts_as_not_unsupported_on_both_sides(self):
        """
        Otherwise a retrieval gap would be scored as a caught
        fabrication, and recall would flatter the judge.
        """
        rows = labelled(
            ("INSUFFICIENT_EVIDENCE", "INSUFFICIENT_EVIDENCE"),
            ("UNSUPPORTED", "UNSUPPORTED"),
        )
        stats = agreement_stats(rows)

        assert stats["agreement"] == 1.0
        assert stats["precision"] == 1.0
        assert stats["false_positives"] == 0

    def test_nothing_validated_yields_zeroes_not_an_error(self):
        stats = agreement_stats([{"evaluator_label": "SUPPORTED", "human_label": None}])

        assert stats["validated_claims"] == 0
        assert stats["agreement"] == 0.0
        assert stats["f1"] == 0.0

    def test_no_unsupported_calls_at_all_gives_zero_precision_not_a_crash(self):
        """
        A judge that never flags anything has no precision to report.
        Zero rather than 1.0: claiming perfect precision for a detector
        that detects nothing is the wrong default.
        """
        stats = agreement_stats(labelled(("SUPPORTED", "SUPPORTED")))

        assert stats["precision"] == 0.0
        assert stats["recall"] == 0.0

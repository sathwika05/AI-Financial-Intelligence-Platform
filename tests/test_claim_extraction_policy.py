"""
What counts as a factual claim, and what is dropped before scoring.

An LLM splits the final answer into candidate assertions, because prose
does not decompose deterministically. Everything after that split is
policy, and policy belongs in code that can be tested without a judge:
which candidates survive, what text is actually checked, and what was
discarded.

THE DEFINITION
    A claim is a verifiable assertion -- a figure, a named-entity fact, a
    comparison, or a direction of travel. "Revenue declined" is checkable.
    "NVDA may benefit from AI demand" is not: no evidence can make a
    hedge false, so scoring it would move the headline rate without
    telling anyone anything.

WHY INTENSIFIERS ARE STRIPPED RATHER THAN FAILED
    "Margins improved significantly" contains a checkable claim and an
    unquantified adverb. Marking the whole thing unsupported because the
    corpus does not define "significant" would inflate the unsupported
    rate with a judgement about wording. The claim evaluated is "Margins
    improved"; the adverb is kept on the record in `original` so a reader
    can see what the answer actually said.

WHY DROPS ARE COUNTED
    An extractor that silently discards two thirds of an answer reports a
    beautiful support rate. The count is the only thing that makes the
    denominator honest.
"""
import pytest

from backend.evaluation.claims.policy import (
    Claim,
    classify_candidates,
    is_about_the_evidence,
    is_speculative,
    numeric_values,
    strip_intensifiers,
)


class TestSpeculationIsNotAClaim:
    @pytest.mark.parametrize(
        "text",
        [
            "NVDA may benefit from continued AI demand.",
            "Intel could outperform its peers next year.",
            "AMD appears well positioned for the coming cycle.",
            "The company seems likely to recover.",
            "Margins might improve if pricing holds.",
        ],
    )
    def test_hedged_statements_are_speculative(self, text):
        assert is_speculative(text) is True

    @pytest.mark.parametrize(
        "text",
        [
            "Revenue grew 12% year over year.",
            "Margins improved.",
            "NVIDIA is a semiconductor company.",
            "NVDA has a higher P/E ratio than INTC.",
            "Demand weakened in the second half.",
        ],
    )
    def test_assertions_are_not_speculative(self, text):
        assert is_speculative(text) is False

    def test_a_reported_expectation_is_still_a_claim(self):
        """
        "Management expects acceleration" asserts something about the
        filings: either management said it or they did not. That is
        checkable, unlike the analyst's own hedge, so the modal test must
        not swallow it.
        """
        assert is_speculative(
            "Management expects revenue acceleration next quarter."
        ) is False


class TestIntensifiersAreStrippedNotFailed:
    @pytest.mark.parametrize(
        "written,checked",
        [
            ("Margins improved significantly.", "Margins improved."),
            ("Revenue declined sharply.", "Revenue declined."),
            ("Demand weakened considerably.", "Demand weakened."),
            ("Costs rose substantially.", "Costs rose."),
        ],
    )
    def test_the_adverb_is_removed(self, written, checked):
        assert strip_intensifiers(written) == checked

    def test_a_claim_with_no_intensifier_is_unchanged(self):
        assert strip_intensifiers("Revenue grew 12%.") == "Revenue grew 12%."

    def test_the_figure_survives_the_strip(self):
        """Stripping must not take the checkable part with it."""
        assert strip_intensifiers(
            "Revenue grew significantly, up 12% year over year."
        ) == "Revenue grew, up 12% year over year."


class TestNumericClaimsAreRecognised:
    @pytest.mark.parametrize(
        "text,expected",
        [
            ("Revenue grew 12%.", ["12%"]),
            ("Its P/E ratio is 33.2.", ["33.2"]),
            ("Market cap reached $2.9 trillion.", ["$2.9"]),
            ("Revenue rose from 8% to 15%.", ["8%", "15%"]),
        ],
    )
    def test_figures_are_extracted(self, text, expected):
        assert numeric_values(text) == expected

    def test_a_directional_claim_carries_no_figures(self):
        assert numeric_values("Margins improved.") == []

    def test_a_ticker_is_not_a_figure(self):
        """
        Tickers and company names are entity facts, not numeric ones. A
        numeric claim triggers the strict arithmetic check, and sending
        "NVDA" through it would ask the judge to verify a number that was
        never asserted.
        """
        assert numeric_values("NVDA leads the group.") == []


class TestClassifyingACandidateList:
    CANDIDATES = [
        "Revenue grew 12% year over year.",
        "Margins improved significantly.",
        "NVDA may benefit from continued AI demand.",
        "Demand weakened in the second half.",
        "The company appears well positioned.",
    ]

    def _result(self):
        return classify_candidates(self.CANDIDATES)

    def test_speculation_is_dropped(self):
        kept = [claim.text for claim in self._result().claims]

        assert "NVDA may benefit from continued AI demand." not in kept
        assert "The company appears well positioned." not in kept

    def test_three_claims_survive(self):
        assert len(self._result().claims) == 3

    def test_what_was_dropped_is_kept_on_the_record(self):
        """
        The denominator has to be auditable. An extractor that drops most
        of an answer reports a flattering rate.
        """
        result = self._result()

        assert result.dropped_count == 2
        assert "The company appears well positioned." in result.dropped

    def test_the_checked_text_has_the_intensifier_removed(self):
        margins = next(
            c for c in self._result().claims if c.text.startswith("Margins")
        )

        assert margins.text == "Margins improved."

    def test_the_original_wording_is_preserved(self):
        """A reader comparing the claim to the answer needs what was written."""
        margins = next(
            c for c in self._result().claims if c.text.startswith("Margins")
        )

        assert margins.original == "Margins improved significantly."

    def test_numeric_claims_are_tagged_for_the_strict_check(self):
        revenue = next(
            c for c in self._result().claims if c.text.startswith("Revenue")
        )

        assert revenue.is_numeric is True

        # A tuple, because Claim is frozen: the figures scored by the judge
        # and the figures written to the row must not be able to diverge.
        assert revenue.numeric_values == ("12%",)

    def test_a_directional_claim_is_not_numeric(self):
        demand = next(
            c for c in self._result().claims if c.text.startswith("Demand")
        )

        assert demand.is_numeric is False

    def test_claims_keep_their_position_in_the_answer(self):
        """
        claim_index is half of the persistence key, so it has to come from
        the extractor rather than from enumerate() at the call site.
        """
        assert [c.index for c in self._result().claims] == [0, 1, 2]

    def test_an_empty_answer_yields_nothing_rather_than_raising(self):
        result = classify_candidates([])

        assert result.claims == []
        assert result.dropped_count == 0

    def test_blank_candidates_are_ignored_entirely(self):
        """Not dropped -- a blank is not a hedge, it is nothing."""
        result = classify_candidates(["", "   ", "Revenue grew 12%."])

        assert len(result.claims) == 1
        assert result.dropped_count == 0


class TestTheClaimRecord:
    def test_a_claim_is_hashable_and_frozen(self):
        """
        Claims are carried through the judge call and back. Freezing them
        keeps the text that was scored identical to the text that is
        stored.
        """
        claim = Claim(
            index=0,
            text="Revenue grew 12%.",
            original="Revenue grew 12%.",
            is_numeric=True,
            numeric_values=("12%",),
        )

        with pytest.raises(Exception):
            claim.text = "something else"  # type: ignore[misc]


class TestStatementsAboutTheEvidenceAreNotClaims:
    """
    An answer describes its own evidence, and those sentences are not
    facts about a company.

        "The available evidence supports the size ranking of NVIDIA."
        "The evidence does not support a stronger recommendation."

    Scoring the first as SUPPORTED is a tautology -- the evidence supports
    what the evidence supports -- and it inflates the support rate with a
    sentence that carries no financial claim at all. Measured on run
    22347774: 15 of 130 extracted claims, 11%, and every one of them
    resolved to SUPPORTED or INSUFFICIENT_EVIDENCE rather than telling
    anyone anything.

    Dropped and counted, like hedges, so the discard stays visible.
    """

    @pytest.mark.parametrize(
        "text",
        [
            "The available evidence supports the size ranking of NVIDIA.",
            "The evidence does not support a stronger investment recommendation.",
            "The limited evidence warrants a neutral recommendation.",
            "The retrieved documents do not mention margins.",
            "No document discusses Apple's guidance.",
            "The available evidence is insufficient for a conviction recommendation.",
        ],
    )
    def test_meta_statements_are_recognised(self, text):
        assert is_about_the_evidence(text) is True

    @pytest.mark.parametrize(
        "text",
        [
            "NVIDIA ranks first by market capitalization.",
            "Revenue grew 12% year over year.",
            "Margins improved.",
            "Apple's market capitalization is $4,543,167,856,640.",
            "Intel supports a lower valuation multiple than NVIDIA.",
        ],
    )
    def test_real_claims_are_not_swept_up(self, text):
        """
        "supports" and "evidence" appear in ordinary financial prose. The
        rule has to key on the sentence being *about* the evidence, not on
        the words appearing anywhere in it.
        """
        assert is_about_the_evidence(text) is False

    def test_they_are_dropped_and_counted(self):
        result = classify_candidates(
            [
                "NVIDIA ranks first by market capitalization.",
                "The available evidence supports the size ranking of NVIDIA.",
            ]
        )

        assert [claim.text for claim in result.claims] == [
            "NVIDIA ranks first by market capitalization."
        ]
        assert result.dropped_count == 1

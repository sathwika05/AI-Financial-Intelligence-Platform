"""
A comparison across companies is not a checkable finding.

Measured on run 22347774, sentiment and mixed routes: 220 claims were not
SUPPORTED, and every one of them had document evidence in context -- a
median of fifteen items. Nothing was starved of retrieval. 70 of the 220
were comparative:

    "Home Depot has the most positive coverage."
    "Walmart ranks second in positivity of news coverage."
    "NVIDIA's coverage is the most positive in this cohort."

None of these can be supported. Retrieved articles discuss one company at
a time, so no single piece of evidence can rank two against each other.
The judge is right to fail them, and no amount of retrieval would change
that.

WHERE IT CAME FROM
    The prompt asked for them. Rule 4 forbids restating figures and
    offered "trades cheaply against the cohort" and "the fastest revenue
    growth here" as the preferred alternative -- both cross-company
    comparisons, both unverifiable by construction.

    So the model was following instructions, and the instructions
    described an ungroundable output.

WHAT REPLACES IT
    The ranking is already computed by the scoring node and rendered as a
    number on the card. Asserting it again in prose adds nothing a reader
    cannot see, and adds a sentence nobody can verify. Each company's own
    evidence is stated instead, and the ranking carries the comparison.
"""
import inspect

from backend.nodes import analysis_node


class TestThePromptForbidsUncheckableComparisons:
    def test_the_rule_is_present(self):
        prompt = analysis_node.SYSTEM_PROMPT.lower()

        assert "comparison" in prompt or "compare" in prompt

    def test_it_names_the_forms_that_fail(self):
        """
        Superlatives, ordinals and relative claims all produce the same
        unverifiable shape, so the rule has to name more than one.
        """
        prompt = analysis_node.SYSTEM_PROMPT.lower()

        assert "superlative" in prompt
        assert "ordinal" in prompt or "ranks second" in prompt

    def test_it_explains_why_rather_than_only_forbidding(self):
        """
        A bare prohibition invites the model to find a synonym. The reason
        -- one article covers one company -- is what generalises.
        """
        prompt = analysis_node.SYSTEM_PROMPT.lower()

        assert "one company" in prompt or "single" in prompt

    def test_it_offers_the_replacement(self):
        """A rule with no alternative produces empty summaries."""
        prompt = analysis_node.SYSTEM_PROMPT

        assert "Not:" in prompt and "Yes:" in prompt


class TestRuleFourNoLongerAsksForComparisons:
    """
    The old examples were the instruction that caused the failures. They
    have to go, or the prompt contradicts itself and the model picks one.
    """

    def test_the_cohort_comparison_example_is_gone(self):
        # Collapsed, because the prompt wraps mid-phrase and a contiguous
        # check would silently pass on "against the\n   cohort".
        flat = " ".join(analysis_node.SYSTEM_PROMPT.split())

        assert "against the cohort" not in flat

    def test_the_superlative_example_is_gone(self):
        flat = " ".join(analysis_node.SYSTEM_PROMPT.split())

        assert "fastest revenue growth here" not in flat

    def test_figures_are_still_left_to_the_database(self):
        """
        The point of rule 4 survives: the model must not retype numbers
        it was shown, because a mistyped figure looks authoritative.
        """
        prompt = analysis_node.SYSTEM_PROMPT

        assert "Do NOT restate" in prompt
        assert "attached to the report from the database" in prompt


class TestTheRulesDoNotContradict:
    def test_the_prompt_still_asks_for_plain_statements(self):
        """
        Rule 8 forbids noncommittal phrasing. Banning comparisons must not
        be read as licence to hedge -- a per-company finding is still a
        plain statement.
        """
        prompt = analysis_node.SYSTEM_PROMPT

        assert "noncommittal" in prompt

    def test_citations_are_still_required(self):
        prompt = analysis_node.SYSTEM_PROMPT

        assert "citation_id" in prompt

    def test_the_rule_numbers_are_unique(self):
        """
        The prompt already had two rules numbered 8. A third duplicate
        makes the list unreadable to the model and to anyone editing it.
        """
        numbers = [
            line.split(".")[0].strip()
            for line in analysis_node.SYSTEM_PROMPT.splitlines()
            if line.split(".")[0].strip().isdigit()
        ]

        assert len(numbers) == len(set(numbers)), f"duplicate rule numbers: {numbers}"

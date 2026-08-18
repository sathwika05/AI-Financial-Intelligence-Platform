"""
Guardrails in the SQL generation prompt.

These are string assertions rather than behavioural ones, which is a real
limitation: they prove the instruction is present, not that the model obeys
it. They exist because each rule here was added after a specific failure, and
a silent edit that drops one would otherwise only surface as a bad benchmark
run days later.

The category rule has now failed twice in different disguises:

  run 1   WHERE c.sector ILIKE '%AI%'          -> 0 rows
  run 2   WHERE EXISTS (SELECT 1 FROM documents d
                        WHERE d.company_id = c.id
                          AND d.content ILIKE '%AI%')

The second selected 35 of 50 companies, because '%AI%' matches the letters
"ai" inside ordinary words — an oil producer qualified because one of its
articles contained "maintains". Fixing only the first disguise is what
allowed the second, so the rule is now written against the behaviour rather
than against one column.
"""
import pathlib

import pytest

from backend.retrieval.sql_executor import get_sector_vocabulary


SOURCE = pathlib.Path("backend/retrieval/sql_executor.py").read_text()


@pytest.fixture(scope="module")
def vocabulary():
    return get_sector_vocabulary()


class TestSectorVocabulary:
    def test_lists_the_real_sectors(self, vocabulary):
        for sector in [
            "Technology",
            "Energy",
            "Healthcare",
            "Industrials",
            "Financial Services",
            "Consumer Cyclical",
            "Consumer Defensive",
            "Communication Services",
        ]:
            assert sector in vocabulary

    def test_states_sector_is_the_only_categorical_column(self, vocabulary):
        assert "ONLY categorical fact" in vocabulary
        assert "no theme column" in vocabulary


class TestCategoryInferenceIsForbidden:
    """Each forbidden pattern is one the model has actually produced."""

    def test_forbids_the_sector_pattern_from_run_one(self, vocabulary):
        assert "WHERE c.sector ILIKE '%AI%'" in vocabulary

    def test_forbids_the_document_pattern_from_run_two(self, vocabulary):
        assert "documents d" in vocabulary
        assert "d.content ILIKE '%AI%'" in vocabulary

    def test_forbids_matching_on_company_name(self, vocabulary):
        assert "WHERE c.name ILIKE '%AI%'" in vocabulary

    def test_explains_that_like_matches_letters_not_meaning(self, vocabulary):
        """
        The reason matters more than the rule. Without it the model treats
        this as arbitrary and finds a third column to abuse.
        """
        assert "letters, not meaning" in vocabulary
        assert "maintains" in vocabulary

    def test_gives_the_two_permitted_alternatives(self, vocabulary):
        assert "c.ticker IN (...)" in vocabulary
        assert "omit the category filter entirely" in vocabulary

    def test_rule_appears_in_the_numbered_rule_list_too(self):
        """
        The vocabulary block sits above the question; the numbered rules are
        the checklist the model works through. The rule needs to be in both.
        """
        assert "NEVER INFER A CATEGORY FROM TEXT" in SOURCE

    def test_verification_checklist_covers_it(self):
        assert "no category is inferred by matching text in any column" in SOURCE


class TestRuleListIsWellFormed:
    def test_rules_are_numbered_without_duplicates(self):
        """A renumbering slip would leave two rules sharing a number."""
        import re

        numbers = re.findall(r"^(\d+)\. [A-Z]", SOURCE, re.MULTILINE)
        assert numbers == sorted(numbers, key=int), numbers
        assert len(numbers) == len(set(numbers)), f"duplicate rule number: {numbers}"

    def test_earlier_guardrails_survive(self):
        """The rules added for previous failures are still present."""
        # Row count, from the question that asked for five and got ten.
        assert "LIMIT must exactly" in SOURCE
        # Identifier column, from the query that omitted ticker and broke ranking.
        assert "c.ticker and c.name" in SOURCE
        assert "This rule outranks" in SOURCE

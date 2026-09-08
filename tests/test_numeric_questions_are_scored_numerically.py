"""
A growth question has to be scored on growth.

"Rank companies with the strongest revenue and EPS growth" returned
Goldman Sachs first with revenue growth of 42.5%, a Growth row weighted
0%, every factor reading N/A, and the verdict "Avoid — poor signals across
dimensions". The signals were not poor. Nothing had been measured.

val_score and growth_score were gated on has_sql, which asks whether the
generated SQL query returned an answer. But score_company_growth reads
company["metrics"], which comes from get_companies_from_db and is always
populated. When the SQL branch came back empty, all four weights were 0.0,
active_weight was 0, the structured score collapsed to 0.0, and the
composite became the LLM's holistic score times 0.3 — so the ranking was
the model's opinion alone, presented beside four metrics that had not
influenced it.

Gated on intent as well as availability. Availability alone is not the
question being asked: a SENTIMENT question has metrics too, and weighting
valuation into it would answer a different question.
"""
from __future__ import annotations

import pytest

from backend.scoring.ranker import (
    _METRICS_DRIVEN_INTENTS,
    get_dynamic_weights,
)


class TestTheNumericDimensionsCarryWeight:
    def test_a_growth_question_weights_growth(self):
        weights = get_dynamic_weights(
            has_sql=True, has_vector=False, has_market=False
        )

        assert weights["growth"] > 0
        assert weights["valuation"] > 0

    def test_nothing_available_still_weights_nothing(self):
        """
        The zero case has to survive: no sources and no metrics means no
        opinion, not a default that quietly becomes the answer.
        """
        weights = get_dynamic_weights(
            has_sql=False, has_vector=False, has_market=False
        )

        assert sum(weights.values()) == 0

    def test_a_sentiment_question_is_unchanged(self):
        weights = get_dynamic_weights(
            has_sql=False, has_vector=True, has_market=False
        )

        assert weights["valuation"] == 0
        assert weights["growth"] == 0
        assert weights["relevance"] > weights["sentiment"] > 0


class TestWhichIntentsAreAnsweredByNumbers:
    @pytest.mark.parametrize("intent", ["VALUATION", "GROWTH"])
    def test_the_numeric_intents(self, intent):
        assert intent in _METRICS_DRIVEN_INTENTS

    @pytest.mark.parametrize("intent", ["SENTIMENT", "MIXED"])
    def test_the_narrative_intents_are_not(self, intent):
        """
        A sentiment question has metrics too. Scoring valuation into it
        would answer a question nobody asked.
        """
        assert intent not in _METRICS_DRIVEN_INTENTS

    def test_it_matches_the_reviewer(self):
        """
        The same question at both ends of the pipeline: does this intent
        get its answer from the metrics table? They must agree, or the
        reviewer will flag evidence the scorer relied on.
        """
        from backend.nodes.reviewer_node import (
            _METRICS_DRIVEN_INTENTS as reviewer_intents,
        )

        assert _METRICS_DRIVEN_INTENTS == reviewer_intents

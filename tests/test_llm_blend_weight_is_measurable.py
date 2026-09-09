"""
The LLM's holistic opinion is worth 30% of the ranking, and nothing chose
that number.

    final_score = round((final_score * 0.7) + (llm_score * 0.3), 3)

Two things make this the hardest question to answer about the ranker.

The weight is arbitrary. There is no measurement behind 0.3 rather than
0.1 or 0.5; it is a constant in the middle of a scoring function.

And the model is not adding independent information. It is handed
"PE=..., Growth=..., EPS=..." -- the same quantities score_company_valuation
and score_company_growth have already turned into numbers -- and then gets
30% of the vote on the result.

Until now the weight could not be varied, so the question could not be
answered either way. It is now configurable per run, on the same
retrieval_flags channel rrf_enabled travels on, so a benchmark can be run
at 0.0, 0.3 and 0.5 and the ranking metrics compared. Two outcomes and
both are useful: either the component earns its weight against the 0.04
noise floor, or it is deleted.

DEFAULT UNCHANGED
    0.3 stays the default, so every existing run and every caller that
    sets nothing gets exactly today's behaviour. This makes the weight
    measurable; it does not pick a new one.
"""
from __future__ import annotations

import pytest

from backend.scoring.ranker import (
    DEFAULT_LLM_BLEND_WEIGHT,
    blend_llm_score,
    llm_blend_weight,
)


class TestTheDefaultIsTodaysBehaviour:
    def test_the_default_is_still_thirty_percent(self):
        assert DEFAULT_LLM_BLEND_WEIGHT == 0.3

    def test_no_config_means_the_default(self):
        assert llm_blend_weight({}) == 0.3

    def test_no_flags_means_the_default(self):
        assert llm_blend_weight({"configurable": {}}) == 0.3

    def test_the_arithmetic_is_unchanged(self):
        """
        0.6 composite, 0.9 from the model: 0.6*0.7 + 0.9*0.3 = 0.69
        """
        assert blend_llm_score(0.6, 0.9, DEFAULT_LLM_BLEND_WEIGHT) == 0.69


class TestTheWeightCanBeVaried:
    @pytest.mark.parametrize("weight", [0.0, 0.1, 0.3, 0.5, 1.0])
    def test_a_run_can_set_it(self, weight):
        config = {
            "configurable": {"retrieval_flags": {"llm_blend_weight": weight}}
        }

        assert llm_blend_weight(config) == weight

    def test_zero_removes_the_model_entirely(self):
        """
        The arm that answers whether the component earns its place.
        """
        assert blend_llm_score(0.6, 0.9, 0.0) == 0.6

    def test_one_hands_the_ranking_to_the_model(self):
        assert blend_llm_score(0.6, 0.9, 1.0) == 0.9


class TestItCannotBeSetToNonsense:
    @pytest.mark.parametrize("weight", [-0.5, 1.5, "high", None])
    def test_an_unusable_weight_falls_back_to_the_default(self, weight):
        """
        A benchmark arm with a garbled weight must run today's pipeline,
        not an undefined one -- otherwise the comparison is silently
        against something nobody chose.
        """
        config = {
            "configurable": {"retrieval_flags": {"llm_blend_weight": weight}}
        }

        assert llm_blend_weight(config) == DEFAULT_LLM_BLEND_WEIGHT


class TestAnAbsentModelScoreChangesNothing:
    def test_no_llm_score_leaves_the_composite_alone(self):
        assert blend_llm_score(0.6, None, 0.3) == 0.6

    def test_that_holds_at_every_weight(self):
        for weight in (0.0, 0.3, 1.0):
            assert blend_llm_score(0.42, None, weight) == 0.42


class TestTheRankerUsesIt:
    def test_the_hardcoded_blend_is_gone(self):
        import inspect

        from backend.scoring import ranker

        source = inspect.getsource(ranker.rerank)

        assert "* 0.7) + (" not in source, (
            "the weight must come from configuration, not a literal"
        )
        assert "blend_llm_score(" in source

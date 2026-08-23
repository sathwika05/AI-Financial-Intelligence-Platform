"""
One metric failing must cost one metric, not the whole evaluation.

_safe_score handles a NaN by returning None, and does nothing about an
exception. RAGAS raised a numpy error — "setting an array element with a
sequence... inhomogeneous shape" — on six questions across four runs:
sentiment_008 twice, mixed_005, mixed_014 and mixed_015. Each time the
whole RAGAS result was discarded and the question recorded 0.0 with no
metrics at all, which the gate then reads as a failure.

That is a measurement lost, not a judgement made. The five other metrics
had already scored or would have.

The composite already skips None, so a metric that returns None simply
does not vote.
"""
import math

import pytest

from backend.evaluation.evaluators.ragas_evaluator import RagasEvaluator


class _Boom:
    """A metric that fails the way RAGAS failed."""

    async def single_turn_ascore(self, sample):
        raise ValueError(
            "setting an array element with a sequence. The requested "
            "array has an inhomogeneous shape after 1 dimensions."
        )


class _Fine:
    def __init__(self, value):
        self.value = value

    async def single_turn_ascore(self, sample):
        return self.value


class _NaN:
    async def single_turn_ascore(self, sample):
        return math.nan


class TestAMetricFailureIsContained:
    @pytest.mark.asyncio
    async def test_a_raising_metric_returns_none(self):
        assert await RagasEvaluator._safe_score(_Boom(), object()) is None

    @pytest.mark.asyncio
    async def test_a_working_metric_still_scores(self):
        assert await RagasEvaluator._safe_score(_Fine(0.75), object()) == 0.75

    @pytest.mark.asyncio
    async def test_nan_still_returns_none(self):
        assert await RagasEvaluator._safe_score(_NaN(), object()) is None

    @pytest.mark.asyncio
    async def test_values_are_still_clamped(self):
        assert await RagasEvaluator._safe_score(_Fine(1.4), object()) == 1.0
        assert await RagasEvaluator._safe_score(_Fine(-0.2), object()) == 0.0

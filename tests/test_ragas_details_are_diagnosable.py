"""
Record what was retrieved, so a low score can be explained.

context_recall separates the mixed set more sharply than any other metric —
0.243 on failures against 0.634 on passes — and three hypotheses about its
cause have each been tested and failed: placement narration in the
reference answer (mixed_003 carries seven such phrases and scores 1.00),
retrieval coverage (correlation -0.05), and figures in the answer (-0.08).

The reason a fourth attempt would also be a guess is that the retrieved
contexts are not stored. details keeps their COUNT, so a question that
scores 0.00 records that fifteen contexts existed and nothing about what
they were. The metric compares reference claims against those contexts, so
without them there is no way to see which claim went unsupported.

Truncated, because the point is identifying which chunk was retrieved, not
re-reading the corpus from the results table.
"""
import inspect

from backend.evaluation.evaluators import ragas_evaluator


class TestTheDetailsExplainTheScore:
    def test_the_retrieved_contexts_are_recorded(self):
        src = inspect.getsource(ragas_evaluator.RagasEvaluator.evaluate)

        assert "retrieved_contexts" in src

    def test_they_are_truncated(self):
        assert ragas_evaluator.CONTEXT_PREVIEW_CHARS <= 400

    def test_the_preview_is_long_enough_to_identify_a_chunk(self):
        assert ragas_evaluator.CONTEXT_PREVIEW_CHARS >= 120

    def test_the_reference_contexts_are_recorded_too(self):
        """
        Recall is reference against retrieved. One side is useless alone.
        """
        src = inspect.getsource(ragas_evaluator.RagasEvaluator.evaluate)

        assert "reference_contexts_preview" in src

    def test_the_counts_are_still_there(self):
        src = inspect.getsource(ragas_evaluator.RagasEvaluator.evaluate)

        assert "context_count" in src

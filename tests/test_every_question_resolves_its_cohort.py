"""
Every benchmark question must resolve to the companies it asks about.

This is the end the resolver exists for. A question whose cohort does not
resolve is answered against the whole corpus, and run c3f5c44b showed what
that costs: ten of twenty-five sentiment questions matched none of their
expected companies, and all four ranking metrics read 0.0 for each.
"""
import pytest

from backend.evaluation.datasets.question_sets import QUESTION_SETS
from backend.retrieval.theme_resolver import resolve_candidates


AUTHORED = [
    question
    for name in ("sentiment", "mixed")
    for question in QUESTION_SETS[name]
    if question.expected_ranking
]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "question",
    AUTHORED,
    ids=[question.question_id for question in AUTHORED],
)
async def test_the_cohort_resolves(question):
    result = await resolve_candidates(
        question.question,
        intent=question.expected_intent.name,
    )

    assert set(result["candidate_tickers"]) == set(question.expected_ranking)

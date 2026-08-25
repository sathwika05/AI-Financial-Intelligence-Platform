"""
The evidence budget is a target, not a ceiling.

Every instruction in the reranker prompt pushes downward — "Select only
useful evidence", "Remove weak or duplicate evidence" — and nothing pushes
toward using the room it has. So it prunes to a minimal set and leaves the
budget unspent.

Run c2ca7bb0, mixed_008: the cohort BLK/SCHW/MS has 13 chunks in the whole
corpus, pgvector returned 12 of them, the reranker saw 18 candidates with
room for 15, and selected 10. Its golden cites 7 contexts, all inside the
cohort, and coverage came out at 29%. Retrieval had found essentially
everything available; the reranker dropped what the reference considers
essential.

That is a precision instruction applied where the failing metric is recall.
Raising CHUNKS_PER_COMPANY and EVIDENCE_PER_COMPANY set a ceiling the model
had no reason to reach.

Duplicate and irrelevant evidence must still go — the point is that
"nothing more to add" has to be the reason for stopping short, rather than
a general preference for brevity.
"""
import inspect

from backend.nodes import reranker_node


class TestTheBudgetIsATarget:
    def test_the_prompt_states_the_budget_as_a_number(self):
        """A budget the model cannot see is a budget it cannot aim at."""
        src = inspect.getsource(reranker_node.rerank_hybrid_contexts)

        assert "{top_k}" in src

    def test_it_says_the_budget_is_a_target_not_a_limit(self):
        src = inspect.getsource(reranker_node.rerank_hybrid_contexts)

        assert "not a limit" in src.lower()

    def test_it_says_what_stopping_short_should_mean(self):
        src = inspect.getsource(reranker_node.rerank_hybrid_contexts)

        assert "nothing" in src.lower() and "add" in src.lower()

    def test_pruning_rules_survive(self):
        """Filling the budget must not become a licence to keep noise."""
        src = inspect.getsource(reranker_node.rerank_hybrid_contexts)

        assert "duplicate" in src.lower()
        assert "Do not invent facts." in src

    def test_the_per_company_floors_survive(self):
        src = inspect.getsource(reranker_node.rerank_hybrid_contexts)

        assert "min_per_company" in src
        assert "min_documents_per_company" in src

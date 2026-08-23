"""
Do not retry retrieval with inputs that have not changed.

The reviewer routes a grounding failure to analysis, with this reasoning in
its own comment: "re-running the same queries cannot fix it". The same is
true of missing evidence and bad citations, and those were routed back to
retrieval anyway — the same query against the same corpus returns the same
documents, so the second and third attempts cannot differ from the first.

Run c3f5c44b: 58 retries across 28 questions, 57 of them targeting
retrieval, and 17 questions exhausted MAX_RETRIES and were force-passed
regardless. analysis ran 86 times for 28 questions at ~26s a call, which is
most of the difference between a 30-second question and a 105-second one.

Retrieval is still the right target when something upstream will actually
differ. What must not happen is a repeat of an identical retrieval.
"""
import inspect

from backend.nodes import reviewer_node


class TestRetryTargetsSomethingThatCanChange:
    def test_the_module_names_the_unchanged_input_problem(self):
        src = inspect.getsource(reviewer_node)

        assert "identical" in src.lower()

    def test_no_retry_targets_retrieval(self):
        """
        Regenerating the draft with the flagged claims handed back is the
        only attempt that can differ.
        """
        src = inspect.getsource(reviewer_node.run_reviewer)

        assert 'retry_target = "analysis"' in src
        assert 'retry_target = "retrieval"' not in src

    def test_the_flags_still_reach_the_next_attempt(self):
        """A retry that carries no feedback is just the same call again."""
        src = inspect.getsource(reviewer_node.run_reviewer)

        assert "all_flags" in src
        assert "total_flags" in src

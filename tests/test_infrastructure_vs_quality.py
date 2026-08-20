"""
"Could not measure" is not "measured zero".

Run 68cce08a recorded mixed_001 at ragas 0.0 with an empty metrics dict.
Nothing about the pipeline had changed — the OpenAI balance ran out while
scoring the last metric, the evaluator threw, and the except branch reported
the strongest possible negative result about retrieval and grounding on the
basis of a billing problem. The question fell from 0.9103 to 0.784 and read
as a regression.

The question still fails, because an unmeasured question is not a passing
one. But the result is tagged so a reader can tell the two apart.
"""
import pytest

from backend.evaluation.evaluators.ragas_evaluator import (
    _is_infrastructure_error,
)


class TestClassification:
    @pytest.mark.parametrize(
        "message",
        [
            "Error code: 429 - {'error': {'code': 'credit_balance_exhausted'}}",
            "insufficient_quota",
            "Rate limit reached for gpt-4",
            "Error code: 401 - invalid_api_key",
            "Connection error.",
            "Request timeout",
        ],
    )
    def test_unreachable_judge_is_infrastructure(self, message):
        assert _is_infrastructure_error(Exception(message))

    @pytest.mark.parametrize(
        "message",
        [
            "KeyError: 'user_input'",
            "ValueError: reference_contexts must be a list",
            "division by zero",
        ],
    )
    def test_real_bugs_are_not_infrastructure(self, message):
        """
        A genuine code fault must keep the loud traceback and must not be
        excused as a billing problem.
        """
        assert not _is_infrastructure_error(Exception(message))

    def test_the_exact_error_from_run_68cce08a(self):
        exc = Exception(
            "Error code: 429 - {'error': {'message': 'You have no credits "
            "remaining. Add credits to continue using the API at "
            "https://platform.openai.com/settings/organization/billing/.', "
            "'type': 'insufficient_quota', 'param': None, 'code': "
            "'credit_balance_exhausted'}}"
        )
        assert _is_infrastructure_error(exc)

    def test_the_exception_type_is_considered_too(self):
        """Some SDKs carry the signal in the class name, not the message."""

        class RateLimitError(Exception):
            pass

        assert _is_infrastructure_error(RateLimitError("no detail"))


class TestResultShape:
    """
    Asserted on source rather than by running the evaluator, which would
    need a live judge — the very thing unavailable here.
    """

    def _source(self):
        import inspect

        from backend.evaluation.evaluators.ragas_evaluator import (
            RagasEvaluator,
        )

        return inspect.getsource(RagasEvaluator.evaluate)

    def test_the_result_is_tagged_unmeasured(self):
        src = self._source()
        assert '"infrastructure_error": infrastructure' in src
        assert '"unmeasured": infrastructure' in src

    def test_it_still_fails_the_question(self):
        """
        An unmeasured question is not a passing one; the tag records why,
        it does not excuse the result.
        """
        src = self._source()
        assert "passed=False" in src

    def test_the_message_says_unreachable_not_failed(self):
        src = self._source()
        assert "could not be measured" in src

    def test_a_real_bug_still_logs_a_traceback(self):
        src = self._source()
        assert "logger.exception" in src

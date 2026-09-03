"""
The audit runs after a question is scored, and cannot break the run.

Two guarantees, and the second is the load-bearing one:

    the audit is attached to the question result
    a failure inside it leaves the question's score untouched

The audit is additional. A judge outage, a malformed answer, or a
splitter that returns prose must cost the run nothing but the claim rows
it would have produced.
"""
from backend.evaluation.benchmark_runner import BenchmarkRunner
from backend.evaluation.claims.audit import ClaimAudit
from backend.evaluation.schemas import PipelineExecution


class TestTheRunnerAudits:
    async def test_the_audit_is_attached_to_the_result(self):
        runner = BenchmarkRunner.__new__(BenchmarkRunner)

        async def splitter(_):
            return '{"claims": ["Revenue grew 12%."]}'

        async def judge(_):
            return (
                '{"verdicts": [{"index": 0, "label": "SUPPORTED",'
                ' "reasoning": "The rows show it."}]}'
            )

        audit = await runner._audit_claims(
            answer="Revenue grew 12%.",
            execution=PipelineExecution(sql_rows=[{"growth": 12}]),
            splitter=splitter,
            judge=judge,
        )

        assert isinstance(audit, ClaimAudit)
        assert audit.total_claims == 1
        assert audit.supported == 1

    async def test_a_broken_judge_yields_an_audit_rather_than_raising(self):
        """
        The question has already been scored by the time this runs.
        Raising here would turn a judge outage into a failed benchmark.
        """
        runner = BenchmarkRunner.__new__(BenchmarkRunner)

        async def splitter(_):
            return '{"claims": ["Revenue grew 12%."]}'

        async def judge(_):
            raise RuntimeError("judge is down")

        audit = await runner._audit_claims(
            answer="Revenue grew 12%.",
            execution=PipelineExecution(sql_rows=[{"growth": 12}]),
            splitter=splitter,
            judge=judge,
        )

        assert audit.total_claims == 1
        assert audit.insufficient_evidence == 1

    async def test_an_answer_that_is_not_text_is_handled(self):
        """
        final_answer is a dict on most routes. The runner has to render it
        before splitting, not hand a dict to a prompt.
        """
        runner = BenchmarkRunner.__new__(BenchmarkRunner)

        async def splitter(prompt):
            assert "top_companies" in prompt or "NVDA" in prompt
            return '{"claims": []}'

        async def judge(_):
            raise AssertionError("no claims, so no judge call")

        audit = await runner._audit_claims(
            answer={"top_companies": [{"ticker": "NVDA"}]},
            execution=PipelineExecution(sql_rows=[{"a": 1}]),
            splitter=splitter,
            judge=judge,
        )

        assert audit.total_claims == 0

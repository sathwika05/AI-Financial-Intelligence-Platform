"""
A run that dies must report what it spent.

total_cost and total_requests are written once, after the whole run. Six
runs in benchmark_runs record $0.00 for that reason, including 64671f10,
which scored 76 of 100 questions over seven hours before the Docker daemon
stopped. The money was spent; the column says zero.

question_results already persists per question (728963c). The run row did
not follow, so a crashed run has its questions but no totals.
"""
import inspect

from backend.api import evaluation_routes


class TestTheRunRowIsUpdatedAsItGoes:
    def test_the_totals_are_written_during_the_run(self):
        src = inspect.getsource(evaluation_routes._execute_benchmark)

        persist = src[src.index("async def persist_one"):]
        persist = persist[: persist.index("benchmark_result = await runner.run")]

        assert "total_cost" in persist
        assert "total_requests" in persist

    def test_a_failing_totals_write_does_not_stop_the_run(self):
        """
        Same rule as the question rows: reporting is a side effect of
        measuring, not the point of it.
        """
        src = inspect.getsource(evaluation_routes._execute_benchmark)

        persist = src[src.index("async def persist_one"):]
        persist = persist[: persist.index("benchmark_result = await runner.run")]

        assert "except Exception" in persist

    def test_the_orphan_sweeper_keeps_what_was_written(self):
        """
        The sweeper marks an interrupted run failed. It must not reset the
        totals it finds there — those are the only record of the spend.
        """
        src = inspect.getsource(evaluation_routes)

        marker = "Orphaned: the API process exited"
        block = src[src.index(marker) - 800 : src.index(marker) + 800]

        assert "total_cost = 0" not in block

"""
The dashboard needs a way to stop a run without restarting the container.

Restarting the API was the only lever until now: it killed the process
mid-question, and the run row read `running` until startup reconciled it
as orphaned. That is how run b94d121d ended.

The endpoint raises a flag; the runner reads it between questions. This
file covers the flag and its guards, not the runner loop, which
test_benchmark_cancellation.py owns.
"""
import uuid

import pytest

from backend.evaluation.schemas import BenchmarkStatus


class TestCancelRequestFlag:
    def test_a_new_run_is_not_cancelled(self):
        """The column has to default false or every run stops at once."""
        from backend.models.db_models import BenchmarkRun

        run = BenchmarkRun(run_id=uuid.uuid4())

        assert run.cancel_requested in (False, None)

    def test_cancelled_is_a_terminal_status(self):
        """
        The dashboard stops polling on terminal statuses. A cancelled run
        that is not terminal would be polled forever.
        """
        from backend.evaluation.schemas import BenchmarkStatus as S

        assert S.CANCELLED.value == "cancelled"
        assert S.CANCELLED is not S.FAILED

    @pytest.mark.asyncio
    async def test_cancelling_an_active_run_raises_the_flag(self):
        from backend.api.evaluation_routes import _request_cancellation

        run = _FakeRun(status="running")
        session = _FakeSession(run)

        await _request_cancellation(
            run_id=run.run_id,
            session=session,
        )

        assert run.cancel_requested is True
        assert session.committed is True

    @pytest.mark.asyncio
    async def test_a_queued_run_can_also_be_cancelled(self):
        """A run stopped before it starts must never begin."""
        from backend.api.evaluation_routes import _request_cancellation

        run = _FakeRun(status="queued")
        session = _FakeSession(run)

        await _request_cancellation(
            run_id=run.run_id,
            session=session,
        )

        assert run.cancel_requested is True

    @pytest.mark.asyncio
    async def test_cancelling_a_finished_run_is_refused(self):
        """
        Nothing is in flight to stop, and flipping the flag on a completed
        run would misreport how it ended.
        """
        from fastapi import HTTPException

        from backend.api.evaluation_routes import _request_cancellation

        run = _FakeRun(status="completed")
        session = _FakeSession(run)

        with pytest.raises(HTTPException) as caught:
            await _request_cancellation(
                run_id=run.run_id,
                session=session,
            )

        assert caught.value.status_code == 409
        assert run.cancel_requested is False

    @pytest.mark.asyncio
    async def test_cancelling_an_unknown_run_is_a_404(self):
        from fastapi import HTTPException

        from backend.api.evaluation_routes import _request_cancellation

        session = _FakeSession(None)

        with pytest.raises(HTTPException) as caught:
            await _request_cancellation(
                run_id=uuid.uuid4(),
                session=session,
            )

        assert caught.value.status_code == 404


class _FakeRun:
    def __init__(self, status):
        self.run_id = uuid.uuid4()
        self.status = status
        self.cancel_requested = False


class _FakeSession:
    """Enough of AsyncSession for the flag path, with no database."""

    def __init__(self, run):
        self._run = run
        self.committed = False

    async def execute(self, _statement):
        return _FakeResult(self._run)

    async def commit(self):
        self.committed = True


class _FakeResult:
    def __init__(self, run):
        self._run = run

    def scalar_one_or_none(self):
        return self._run


class TestCancelledRunTotals:
    """
    A cancelled run must report what it actually scored.

    total_requests was written from the question set's size, which equals
    the scored count on every run that finishes — so the bug stayed
    invisible until a run stopped early. Cancelled run f55fda6e reported
    30 requests having scored 1, at a cost of $0.0298.
    """

    def test_the_count_is_the_questions_actually_scored(self):
        from backend.api.evaluation_routes import _scored_question_count

        result = _FakeBenchmarkResult(
            total_questions=30,
            scored=1,
        )

        assert _scored_question_count(result) == 1

    def test_a_complete_run_is_unchanged(self):
        """The ordinary path must report exactly what it always did."""
        from backend.api.evaluation_routes import _scored_question_count

        result = _FakeBenchmarkResult(
            total_questions=30,
            scored=30,
        )

        assert _scored_question_count(result) == 30


class _FakeBenchmarkResult:
    def __init__(self, total_questions, scored):
        self.total_questions = total_questions
        self.question_results = [object()] * scored

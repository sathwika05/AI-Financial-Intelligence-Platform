"""
An escalation an administrator cannot open is not an escalation.

Withholding the ranking from the analyst is only half of it. The other half
is that the withheld ranking has to survive somewhere an admin can read it,
along with enough of the run to judge whether the low confidence was the
pipeline being honest or the pipeline being broken.

That is why the row stores the draft rather than the response. The response
is the redacted one -- top_companies is empty by the time it leaves the
reviewer, so a row built from it would tell an admin only that something
was withheld, never what.

Runs inside a transaction that is rolled back, so no escalation survives
the test.
"""
import pytest
from sqlalchemy import select

from backend.escalation.service import (
    list_escalations,
    record_escalation,
    resolve_escalation,
)
from backend.models.db_models import Escalation
from backend.services.postgres_service import AsyncSessionLocal


WITHHELD = {
    "query_summary": "Rank three semiconductor companies",
    "intent": "SENTIMENT",
    "overall_confidence": 0.17,
    "companies": [
        {"ticker": "INTC", "confidence": 0.2, "rationale": "thin coverage"},
        {"ticker": "NVDA", "confidence": 0.14, "rationale": "thin coverage"},
    ],
}

ESCALATED_RESPONSE = {
    "query_summary": "Rank three semiconductor companies",
    "intent": "SENTIMENT",
    "top_companies": [],
    "withheld": True,
    "overall_confidence": 0.17,
    "review": {
        "escalated": True,
        "notice": "Confidence in this answer is 0.17, below the 0.30 floor.",
        "decision": "forced_pass",
        "flags": ["INTC: confidence 0.20 is below threshold 0.70"],
    },
}


@pytest.fixture
async def db():
    """A session whose work is always rolled back."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.rollback()


class TestRecording:
    async def test_an_escalated_report_is_written(self, db):
        row = await record_escalation(
            db,
            query="Which semiconductor company has the best coverage?",
            final_report=ESCALATED_RESPONSE,
            draft_report=WITHHELD,
        )

        assert row is not None
        assert row.id is not None

    async def test_a_healthy_report_writes_nothing(self, db):
        """
        The route calls this on every query. Deciding here rather than at
        the call site is what keeps the condition in one place.
        """
        healthy = {
            "top_companies": [{"ticker": "NVDA"}],
            "withheld": False,
            "overall_confidence": 0.88,
            "review": {"escalated": False, "notice": None},
        }

        before = len((await db.execute(select(Escalation))).scalars().all())

        row = await record_escalation(
            db,
            query="Which semiconductor company has the best coverage?",
            final_report=healthy,
            draft_report={"companies": [{"ticker": "NVDA"}]},
        )
        after = len((await db.execute(select(Escalation))).scalars().all())

        assert row is None
        assert after == before

    async def test_it_keeps_what_the_analyst_did_not_see(self, db):
        """The reason the row exists."""
        row = await record_escalation(
            db,
            query="Which semiconductor company has the best coverage?",
            final_report=ESCALATED_RESPONSE,
            draft_report=WITHHELD,
        )

        tickers = [c["ticker"] for c in row.withheld_report["companies"]]

        assert tickers == ["INTC", "NVDA"]

    async def test_it_keeps_the_question_and_the_number(self, db):
        row = await record_escalation(
            db,
            query="Which semiconductor company has the best coverage?",
            final_report=ESCALATED_RESPONSE,
            draft_report=WITHHELD,
        )

        assert row.query == "Which semiconductor company has the best coverage?"
        assert row.confidence == pytest.approx(0.17)
        assert row.intent == "SENTIMENT"

    async def test_it_keeps_the_flags_that_explain_the_score(self, db):
        """
        Without these an admin sees a low number and no account of why,
        which makes every row a re-investigation from scratch.
        """
        row = await record_escalation(
            db,
            query="Which semiconductor company has the best coverage?",
            final_report=ESCALATED_RESPONSE,
            draft_report=WITHHELD,
        )

        assert row.review_flags == [
            "INTC: confidence 0.20 is below threshold 0.70"
        ]

    async def test_a_new_row_is_pending(self, db):
        row = await record_escalation(
            db,
            query="Which semiconductor company has the best coverage?",
            final_report=ESCALATED_RESPONSE,
            draft_report=WITHHELD,
        )

        assert row.status == "pending"
        assert row.reviewed_by is None


class TestListing:
    async def test_pending_rows_come_back(self, db):
        await record_escalation(
            db,
            query="A question needing review",
            final_report=ESCALATED_RESPONSE,
            draft_report=WITHHELD,
        )

        rows = await list_escalations(db, status="pending")

        assert any(r.query == "A question needing review" for r in rows)

    async def test_newest_first(self, db):
        """An admin opens the queue to see what just happened."""
        for text in ("older question", "newer question"):
            await record_escalation(
                db,
                query=text,
                final_report=ESCALATED_RESPONSE,
                draft_report=WITHHELD,
            )

        rows = await list_escalations(db, status="pending")
        queries = [r.query for r in rows]

        assert queries.index("newer question") < queries.index("older question")

    async def test_resolved_rows_are_not_in_the_pending_queue(self, db):
        row = await record_escalation(
            db,
            query="Already handled",
            final_report=ESCALATED_RESPONSE,
            draft_report=WITHHELD,
        )
        await resolve_escalation(
            db,
            escalation_id=row.id,
            status="resolved",
            note="Corpus genuinely thin here.",
            reviewer="admin@example.com",
        )

        pending = await list_escalations(db, status="pending")

        assert all(r.query != "Already handled" for r in pending)


class TestResolving:
    async def test_it_records_who_and_what_they_said(self, db):
        row = await record_escalation(
            db,
            query="Needs a decision",
            final_report=ESCALATED_RESPONSE,
            draft_report=WITHHELD,
        )

        resolved = await resolve_escalation(
            db,
            escalation_id=row.id,
            status="resolved",
            note="Coverage is thin; the low score is correct.",
            reviewer="admin@example.com",
        )

        assert resolved.status == "resolved"
        assert resolved.reviewed_by == "admin@example.com"
        assert resolved.resolution_note == (
            "Coverage is thin; the low score is correct."
        )
        assert resolved.reviewed_at is not None

    async def test_an_unknown_id_returns_nothing_rather_than_raising(self, db):
        """The route turns this into a 404; an exception would be a 500."""
        assert await resolve_escalation(
            db,
            escalation_id=99_999_999,
            status="resolved",
            note="",
            reviewer="admin@example.com",
        ) is None

    async def test_an_unknown_status_is_refused(self, db):
        """
        Status drives the admin queue. A typo'd value would silently
        remove a row from the pending list without resolving it.
        """
        row = await record_escalation(
            db,
            query="Needs a decision",
            final_report=ESCALATED_RESPONSE,
            draft_report=WITHHELD,
        )

        with pytest.raises(ValueError):
            await resolve_escalation(
                db,
                escalation_id=row.id,
                status="donezo",
                note="",
                reviewer="admin@example.com",
            )

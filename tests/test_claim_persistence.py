"""
Storing claims, and letting a human label them.

The one rule that matters: re-running the evaluator replaces its own
label and never touches the human's. The entire value of the validation
page is comparing the two, which is impossible if either can quietly
overwrite the other.
"""
from uuid import uuid4

import pytest
from sqlalchemy import text

from backend.evaluation.claims.audit import ClaimAudit, ClaimRecord
from backend.evaluation.claims.store import (
    claims_for_run,
    save_human_label,
    upsert_claims,
)
from backend.services.postgres_service import AsyncSessionLocal, engine


@pytest.fixture
async def run_id():
    """A benchmark_runs row to hang claims off, removed afterwards."""
    identifier = uuid4()

    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO benchmark_runs (run_id, status, dataset, "
                "question_set, model, retrieval_mode) VALUES "
                "(:id, 'completed', 'test', 'all', 'test', 'hybrid')"
            ),
            {"id": identifier},
        )

    yield identifier

    async with engine.begin() as conn:
        await conn.execute(
            text("DELETE FROM claim_evaluations WHERE run_id = :id"),
            {"id": identifier},
        )
        await conn.execute(
            text("DELETE FROM benchmark_runs WHERE run_id = :id"),
            {"id": identifier},
        )


@pytest.fixture
async def db():
    async with AsyncSessionLocal() as session:
        yield session


def audit(label="UNSUPPORTED", claim="Revenue grew 12%."):
    return ClaimAudit(
        claims=[
            ClaimRecord(
                index=0,
                claim=claim,
                original=claim,
                is_numeric=True,
                numeric_values=("12%",),
                evidence=["[sql] {\"ticker\": \"NVDA\"}"],
                label=label,
                reasoning="A reason.",
                evaluator_model="gpt-4o-mini",
            ),
            ClaimRecord(
                index=1,
                claim="Margins improved.",
                original="Margins improved significantly.",
                evidence=["[document] a chunk"],
                label="SUPPORTED",
                reasoning="Another reason.",
                evaluator_model="gpt-4o-mini",
            ),
        ],
        dropped=["NVDA may benefit."],
    )


class TestWriting:
    async def test_a_row_per_claim(self, db, run_id):
        await upsert_claims(
            db, run_id=run_id, question_id="mixed_002",
            route="MIXED", audit=audit(),
        )
        await db.commit()

        assert len(await claims_for_run(db, run_id=run_id)) == 2

    async def test_the_fields_survive_the_round_trip(self, db, run_id):
        await upsert_claims(
            db, run_id=run_id, question_id="mixed_002",
            route="MIXED", audit=audit(),
        )
        await db.commit()

        row = (await claims_for_run(db, run_id=run_id))[0]

        assert row["claim"] == "Revenue grew 12%."
        assert row["evaluator_label"] == "UNSUPPORTED"
        assert row["is_numeric"] is True
        assert row["route"] == "MIXED"
        assert row["evaluator_model"] == "gpt-4o-mini"

    async def test_the_evidence_is_stored_with_the_claim(self, db, run_id):
        """The validation page cannot ask a human without showing it."""
        await upsert_claims(
            db, run_id=run_id, question_id="mixed_002",
            route="MIXED", audit=audit(),
        )
        await db.commit()

        row = (await claims_for_run(db, run_id=run_id))[0]

        assert row["evidence"] == ['[sql] {"ticker": "NVDA"}']

    async def test_the_original_wording_is_kept_beside_the_checked_text(
        self, db, run_id
    ):
        await upsert_claims(
            db, run_id=run_id, question_id="mixed_002",
            route="MIXED", audit=audit(),
        )
        await db.commit()

        margins = [
            row for row in await claims_for_run(db, run_id=run_id)
            if row["claim_index"] == 1
        ][0]

        assert margins["claim"] == "Margins improved."
        assert margins["original"] == "Margins improved significantly."

    async def test_re_running_updates_rather_than_duplicating(self, db, run_id):
        for _ in range(2):
            await upsert_claims(
                db, run_id=run_id, question_id="mixed_002",
                route="MIXED", audit=audit(),
            )
            await db.commit()

        assert len(await claims_for_run(db, run_id=run_id)) == 2

    async def test_an_empty_audit_writes_nothing(self, db, run_id):
        await upsert_claims(
            db, run_id=run_id, question_id="mixed_002",
            route="MIXED", audit=ClaimAudit(),
        )
        await db.commit()

        assert await claims_for_run(db, run_id=run_id) == []


class TestHumanLabels:
    async def _one(self, db, run_id):
        await upsert_claims(
            db, run_id=run_id, question_id="mixed_002",
            route="MIXED", audit=audit(),
        )
        await db.commit()

        return (await claims_for_run(db, run_id=run_id))[0]["id"]

    async def test_a_human_label_is_stored(self, db, run_id):
        claim_id = await self._one(db, run_id)

        await save_human_label(
            db, claim_id=claim_id, label="SUPPORTED",
            labeled_by="sathwikap25@gmail.com",
        )
        await db.commit()

        row = (await claims_for_run(db, run_id=run_id))[0]

        assert row["human_label"] == "SUPPORTED"
        assert row["human_labeled_by"] == "sathwikap25@gmail.com"
        assert row["human_labeled_at"] is not None

    async def test_the_evaluator_label_is_not_touched(self, db, run_id):
        claim_id = await self._one(db, run_id)

        await save_human_label(
            db, claim_id=claim_id, label="SUPPORTED", labeled_by="me",
        )
        await db.commit()

        row = (await claims_for_run(db, run_id=run_id))[0]

        assert row["evaluator_label"] == "UNSUPPORTED"

    async def test_re_running_the_evaluator_keeps_the_human_label(
        self, db, run_id
    ):
        """
        The rule the table exists for. A second benchmark writes a new
        evaluator label over the same claim; the human's verdict has to
        survive, or agreement can never be computed across runs.
        """
        claim_id = await self._one(db, run_id)

        await save_human_label(
            db, claim_id=claim_id, label="SUPPORTED", labeled_by="me",
        )
        await db.commit()

        await upsert_claims(
            db, run_id=run_id, question_id="mixed_002",
            route="MIXED", audit=audit(label="INSUFFICIENT_EVIDENCE"),
        )
        await db.commit()

        row = (await claims_for_run(db, run_id=run_id))[0]

        assert row["human_label"] == "SUPPORTED"
        assert row["evaluator_label"] == "INSUFFICIENT_EVIDENCE"

    async def test_an_unknown_label_is_refused(self, db, run_id):
        """
        A label outside the three would be counted as a disagreement by
        the agreement maths and would never match anything.
        """
        claim_id = await self._one(db, run_id)

        with pytest.raises(ValueError):
            await save_human_label(
                db, claim_id=claim_id, label="PROBABLY", labeled_by="me",
            )

    async def test_a_missing_claim_is_reported_rather_than_ignored(self, db):
        with pytest.raises(LookupError):
            await save_human_label(
                db, claim_id=99_999_999, label="SUPPORTED", labeled_by="me",
            )


class TestReading:
    async def test_claims_come_back_in_a_stable_order(self, db, run_id):
        """
        A validation page that reshuffles between refreshes makes
        labelling fifty claims miserable.
        """
        await upsert_claims(
            db, run_id=run_id, question_id="mixed_002",
            route="MIXED", audit=audit(),
        )
        await db.commit()

        rows = await claims_for_run(db, run_id=run_id)

        assert [row["claim_index"] for row in rows] == [0, 1]

    async def test_unlabelled_claims_can_be_isolated(self, db, run_id):
        """The labelling queue: what still needs a human."""
        await upsert_claims(
            db, run_id=run_id, question_id="mixed_002",
            route="MIXED", audit=audit(),
        )
        await db.commit()

        first = (await claims_for_run(db, run_id=run_id))[0]["id"]

        await save_human_label(
            db, claim_id=first, label="SUPPORTED", labeled_by="me",
        )
        await db.commit()

        remaining = await claims_for_run(db, run_id=run_id, unlabeled=True)

        assert len(remaining) == 1
        assert remaining[0]["claim_index"] == 1

    async def test_a_label_filter_narrows_the_list(self, db, run_id):
        await upsert_claims(
            db, run_id=run_id, question_id="mixed_002",
            route="MIXED", audit=audit(),
        )
        await db.commit()

        rows = await claims_for_run(
            db, run_id=run_id, label="UNSUPPORTED"
        )

        assert len(rows) == 1
        assert rows[0]["evaluator_label"] == "UNSUPPORTED"

    async def test_the_limit_is_respected(self, db, run_id):
        await upsert_claims(
            db, run_id=run_id, question_id="mixed_002",
            route="MIXED", audit=audit(),
        )
        await db.commit()

        assert len(await claims_for_run(db, run_id=run_id, limit=1)) == 1

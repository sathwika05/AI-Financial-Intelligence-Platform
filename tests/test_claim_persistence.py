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
    count_claims_for_run,
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
            text("DELETE FROM question_results WHERE run_id = :id"),
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


class TestSeparatingLabelledFromUnlabelled:
    """
    The validation page needs both halves of the queue.

    Labelling only the claims the judge called UNSUPPORTED measures
    precision and nothing else: a fabrication the judge waved through as
    SUPPORTED never appears in that filter, so recall stays unmeasurable.
    Reading back what has already been labelled is how a session is
    resumed without starting again.
    """

    async def _two(self, db, run_id):
        await upsert_claims(
            db, run_id=run_id, question_id="mixed_002",
            route="MIXED", audit=audit(),
        )
        await db.commit()

        rows = await claims_for_run(db, run_id=run_id)
        await save_human_label(
            db, claim_id=rows[0]["id"], label="SUPPORTED", labeled_by="me",
        )
        await db.commit()

        return rows

    async def test_only_the_labelled_come_back(self, db, run_id):
        await self._two(db, run_id)

        rows = await claims_for_run(db, run_id=run_id, labeled=True)

        assert len(rows) == 1
        assert rows[0]["human_label"] == "SUPPORTED"

    async def test_only_the_unlabelled_come_back(self, db, run_id):
        await self._two(db, run_id)

        rows = await claims_for_run(db, run_id=run_id, unlabeled=True)

        assert len(rows) == 1
        assert rows[0]["human_label"] is None

    async def test_the_two_halves_add_up_to_everything(self, db, run_id):
        await self._two(db, run_id)

        done = await claims_for_run(db, run_id=run_id, labeled=True)
        todo = await claims_for_run(db, run_id=run_id, unlabeled=True)
        every = await claims_for_run(db, run_id=run_id)

        assert len(done) + len(todo) == len(every)

    async def test_a_label_filter_combines_with_the_labelled_filter(
        self, db, run_id
    ):
        """
        "Unsupported claims I have not read yet" is the query a labelling
        session actually runs.
        """
        await self._two(db, run_id)

        rows = await claims_for_run(
            db, run_id=run_id, label="SUPPORTED", unlabeled=True,
        )

        assert [r["claim_index"] for r in rows] == [1]

    async def test_asking_for_both_halves_at_once_is_refused(self, db, run_id):
        """
        Labelled and unlabelled are complements. A caller passing both has
        a bug, and silently returning nothing would hide it.
        """
        with pytest.raises(ValueError):
            await claims_for_run(
                db, run_id=run_id, labeled=True, unlabeled=True,
            )


class TestPaging:
    """
    A hundred-question run is over a thousand claims. Loading them all to
    show twenty-five is wasteful, and a table that long is unusable — so
    the queue is paged, and the page has to know the size of the set it is
    a slice of.
    """

    async def _five(self, db, run_id):
        await upsert_claims(
            db, run_id=run_id, question_id="q1", route="MIXED", audit=audit(),
        )
        await upsert_claims(
            db, run_id=run_id, question_id="q2", route="MIXED", audit=audit(),
        )
        await db.commit()

    async def test_offset_skips_the_earlier_rows(self, db, run_id):
        await self._five(db, run_id)

        every = await claims_for_run(db, run_id=run_id)
        second = await claims_for_run(db, run_id=run_id, offset=1, limit=1)

        assert second[0]["id"] == every[1]["id"]

    async def test_a_page_is_the_size_it_asked_for(self, db, run_id):
        await self._five(db, run_id)

        assert len(await claims_for_run(db, run_id=run_id, limit=2)) == 2

    async def test_paging_past_the_end_is_empty_rather_than_an_error(
        self, db, run_id
    ):
        await self._five(db, run_id)

        assert await claims_for_run(db, run_id=run_id, offset=500) == []

    async def test_the_pages_reconstruct_the_whole_set(self, db, run_id):
        """Nothing lost or duplicated between page boundaries."""
        await self._five(db, run_id)

        every = [row["id"] for row in await claims_for_run(db, run_id=run_id)]

        paged: list[int] = []
        for offset in range(0, len(every), 2):
            page = await claims_for_run(
                db, run_id=run_id, offset=offset, limit=2
            )
            paged.extend(row["id"] for row in page)

        assert paged == every

    async def test_the_total_counts_the_set_not_the_page(self, db, run_id):
        """
        "1-25 of 1072" needs the 1072, and a page of 25 cannot supply it.
        """
        await self._five(db, run_id)

        assert await count_claims_for_run(db, run_id=run_id) == 4

    async def test_the_total_respects_the_filters(self, db, run_id):
        """
        Otherwise "showing 1-25 of 1072" appears above a filtered list of
        three, and Next pages through nothing.
        """
        await self._five(db, run_id)

        assert await count_claims_for_run(
            db, run_id=run_id, label="UNSUPPORTED"
        ) == 2


class TestTheQuestionTravelsWithTheClaim:
    """
    A claim cannot be judged without the question behind it.

    "Chevron ranks second, with revenue growth below EOG" is impossible to
    label from `growth_cheap_30 · GROWTH` alone -- second among which
    companies, and under what filter? The question text answers both.

    Joined from question_results rather than copied onto every claim row:
    one question produces around ten claims, and ten copies of the same
    sentence is ten chances for them to disagree after a re-run.
    """

    async def _with_question(self, db, run_id):
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO question_results "
                    "(run_id, question_id, question, expected_intent, passed) "
                    "VALUES (:r, 'mixed_002', :q, 'MIXED', true)"
                ),
                {
                    "r": run_id,
                    "q": "Among companies trading below a P/E of 30, which "
                         "five have the strongest revenue growth?",
                },
            )

        await upsert_claims(
            db, run_id=run_id, question_id="mixed_002",
            route="MIXED", audit=audit(),
        )
        await db.commit()

    async def test_the_question_text_comes_back_on_the_claim(
        self, db, run_id
    ):
        await self._with_question(db, run_id)

        rows = await claims_for_run(db, run_id=run_id)

        assert rows[0]["question"].startswith("Among companies trading below")

    async def test_every_claim_from_that_question_carries_it(
        self, db, run_id
    ):
        await self._with_question(db, run_id)

        rows = await claims_for_run(db, run_id=run_id)

        assert len({row["question"] for row in rows}) == 1
        assert len(rows) == 2

    async def test_a_claim_with_no_question_row_still_loads(self, db, run_id):
        """
        The join must not drop claims. A question row can be missing --
        an older run, or a persist that failed after the claims landed --
        and losing the claim would be far worse than losing its caption.
        """
        await upsert_claims(
            db, run_id=run_id, question_id="orphan_01",
            route="MIXED", audit=audit(),
        )
        await db.commit()

        rows = await claims_for_run(db, run_id=run_id)

        assert len(rows) == 2
        assert rows[0]["question"] is None

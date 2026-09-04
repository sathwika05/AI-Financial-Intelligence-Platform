"""
The three endpoints the validation page needs.

    GET   /api/evaluation/runs/{run_id}/claims          the labelling queue
    GET   /api/evaluation/runs/{run_id}/claims/summary  rates + agreement
    PATCH /api/evaluation/claims/{claim_id}             one human verdict

Admin-only, like the rest of the evaluation surface: a claim row carries
the answer's own text and the evidence behind it, which is more of the
corpus than an analyst endpoint hands out.
"""
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from backend.auth.tokens import create_access_token
from backend.evaluation.claims.audit import ClaimAudit, ClaimRecord
from backend.evaluation.claims.store import upsert_claims
from backend.main import app
from backend.services.postgres_service import AsyncSessionLocal, engine


def _headers(role="admin"):
    token = create_access_token(subject="tester@example.com", role=role)

    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def client():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as session:
        yield session


@pytest.fixture
async def seeded():
    """A run with three claims: supported, unsupported, insufficient."""
    run_id = uuid4()

    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO benchmark_runs (run_id, status, dataset, "
                "question_set, model, retrieval_mode) VALUES "
                "(:id, 'completed', 'test', 'all', 'test', 'hybrid')"
            ),
            {"id": run_id},
        )

    audit = ClaimAudit(
        claims=[
            ClaimRecord(
                index=index,
                claim=f"Claim {index}.",
                original=f"Claim {index}.",
                evidence=["[document] a chunk"],
                label=label,
                reasoning="because",
                evaluator_model="gpt-4o-mini",
            )
            for index, label in enumerate(
                ["SUPPORTED", "UNSUPPORTED", "INSUFFICIENT_EVIDENCE"]
            )
        ],
        dropped=["NVDA may benefit."],
    )

    async with AsyncSessionLocal() as session:
        await upsert_claims(
            session, run_id=run_id, question_id="mixed_002",
            route="MIXED", audit=audit,
        )
        await session.commit()

    yield run_id

    async with engine.begin() as conn:
        await conn.execute(
            text("DELETE FROM claim_evaluations WHERE run_id = :id"),
            {"id": run_id},
        )
        await conn.execute(
            text("DELETE FROM benchmark_runs WHERE run_id = :id"),
            {"id": run_id},
        )


class TestListingClaims:
    async def test_an_admin_gets_the_claims(self, client, seeded):
        response = await client.get(
            f"/api/evaluation/runs/{seeded}/claims", headers=_headers()
        )

        assert response.status_code == 200
        assert len(response.json()["items"]) == 3

    async def test_a_claim_carries_its_evidence_and_reasoning(
        self, client, seeded
    ):
        """A human cannot label a claim shown without either."""
        row = (
            await client.get(
                f"/api/evaluation/runs/{seeded}/claims", headers=_headers()
            )
        ).json()["items"][0]

        assert row["evidence"] == ["[document] a chunk"]
        assert row["evaluator_reasoning"] == "because"

    async def test_the_queue_can_be_narrowed_to_unlabelled(
        self, client, seeded
    ):
        response = await client.get(
            f"/api/evaluation/runs/{seeded}/claims?unlabeled=true",
            headers=_headers(),
        )

        assert len(response.json()["items"]) == 3

    async def test_a_label_filter_is_applied(self, client, seeded):
        response = await client.get(
            f"/api/evaluation/runs/{seeded}/claims?label=UNSUPPORTED",
            headers=_headers(),
        )

        assert len(response.json()["items"]) == 1

    async def test_an_analyst_is_refused(self, client, seeded):
        """
        A claim row carries the answer text and the evidence behind it —
        more of the corpus than the analyst surface hands out.
        """
        response = await client.get(
            f"/api/evaluation/runs/{seeded}/claims",
            headers=_headers(role="analyst"),
        )

        assert response.status_code in (401, 403)

    async def test_signing_in_is_required(self, client, seeded):
        response = await client.get(f"/api/evaluation/runs/{seeded}/claims")

        assert response.status_code in (401, 403)


class TestTheSummary:
    async def test_the_rates_are_reported(self, client, seeded):
        body = (
            await client.get(
                f"/api/evaluation/runs/{seeded}/claims/summary",
                headers=_headers(),
            )
        ).json()

        assert body["total_claims"] == 3
        assert body["supported"] == 1
        assert body["unsupported"] == 1
        assert body["insufficient_evidence"] == 1

    async def test_the_support_rate_is_computed(self, client, seeded):
        body = (
            await client.get(
                f"/api/evaluation/runs/{seeded}/claims/summary",
                headers=_headers(),
            )
        ).json()

        assert body["claim_support_rate"] == pytest.approx(1 / 3, abs=5e-5)
        assert body["unsupported_fact_rate"] == pytest.approx(1 / 3, abs=5e-5)

    async def test_agreement_is_included_and_starts_empty(
        self, client, seeded
    ):
        body = (
            await client.get(
                f"/api/evaluation/runs/{seeded}/claims/summary",
                headers=_headers(),
            )
        ).json()

        assert body["validated_claims"] == 0
        assert body["agreement"] == 0.0

    async def test_a_run_with_no_claims_summarises_to_zero(self, client):
        body = (
            await client.get(
                f"/api/evaluation/runs/{uuid4()}/claims/summary",
                headers=_headers(),
            )
        ).json()

        assert body["total_claims"] == 0
        assert body["claim_support_rate"] == 0.0


class TestLabelling:
    async def _first_claim_id(self, client, run_id):
        rows = (
            await client.get(
                f"/api/evaluation/runs/{run_id}/claims", headers=_headers()
            )
        ).json()["items"]

        return rows[0]["id"]

    async def test_a_human_label_is_saved(self, client, seeded):
        claim_id = await self._first_claim_id(client, seeded)

        response = await client.patch(
            f"/api/evaluation/claims/{claim_id}",
            json={"human_label": "UNSUPPORTED"},
            headers=_headers(),
        )

        assert response.status_code == 200
        assert response.json()["human_label"] == "UNSUPPORTED"

    async def test_the_evaluator_label_is_untouched(self, client, seeded):
        claim_id = await self._first_claim_id(client, seeded)

        body = (
            await client.patch(
                f"/api/evaluation/claims/{claim_id}",
                json={"human_label": "UNSUPPORTED"},
                headers=_headers(),
            )
        ).json()

        assert body["evaluator_label"] == "SUPPORTED"

    async def test_the_labeller_is_recorded(self, client, seeded):
        """Who said so, for a page whose whole output is human judgement."""
        claim_id = await self._first_claim_id(client, seeded)

        body = (
            await client.patch(
                f"/api/evaluation/claims/{claim_id}",
                json={"human_label": "UNSUPPORTED"},
                headers=_headers(),
            )
        ).json()

        assert body["human_labeled_by"] == "tester@example.com"

    async def test_labelling_moves_the_agreement_numbers(
        self, client, seeded
    ):
        """
        The claim labelled here is SUPPORTED by the evaluator and
        UNSUPPORTED by the human: a false negative, the expensive kind.
        """
        claim_id = await self._first_claim_id(client, seeded)

        await client.patch(
            f"/api/evaluation/claims/{claim_id}",
            json={"human_label": "UNSUPPORTED"},
            headers=_headers(),
        )

        body = (
            await client.get(
                f"/api/evaluation/runs/{seeded}/claims/summary",
                headers=_headers(),
            )
        ).json()

        assert body["validated_claims"] == 1
        assert body["false_negatives"] == 1
        assert body["agreement"] == 0.0

    async def test_an_unknown_label_is_rejected(self, client, seeded):
        claim_id = await self._first_claim_id(client, seeded)

        response = await client.patch(
            f"/api/evaluation/claims/{claim_id}",
            json={"human_label": "PROBABLY"},
            headers=_headers(),
        )

        assert response.status_code == 422

    async def test_a_missing_claim_is_a_404(self, client):
        response = await client.patch(
            "/api/evaluation/claims/99999999",
            json={"human_label": "SUPPORTED"},
            headers=_headers(),
        )

        assert response.status_code == 404

    async def test_an_analyst_cannot_label(self, client, seeded):
        claim_id = await self._first_claim_id(client, seeded)

        response = await client.patch(
            f"/api/evaluation/claims/{claim_id}",
            json={"human_label": "SUPPORTED"},
            headers=_headers(role="analyst"),
        )

        assert response.status_code in (401, 403)


class TestTheLabellingFilters:
    async def test_unlabelled_is_the_default_queue(self, client, seeded):
        response = await client.get(
            f"/api/evaluation/runs/{seeded}/claims?unlabeled=true",
            headers=_headers(),
        )

        assert len(response.json()["items"]) == 3

    async def test_labelled_comes_back_separately(self, client, seeded):
        rows = (
            await client.get(
                f"/api/evaluation/runs/{seeded}/claims", headers=_headers()
            )
        ).json()["items"]

        await client.patch(
            f"/api/evaluation/claims/{rows[0]['id']}",
            json={"human_label": "SUPPORTED"},
            headers=_headers(),
        )

        done = (
            await client.get(
                f"/api/evaluation/runs/{seeded}/claims?labeled=true",
                headers=_headers(),
            )
        ).json()
        todo = (
            await client.get(
                f"/api/evaluation/runs/{seeded}/claims?unlabeled=true",
                headers=_headers(),
            )
        ).json()

        assert len(done["items"]) == 1
        assert len(todo["items"]) == 2

    async def test_the_filters_combine(self, client, seeded):
        """"Unsupported claims I have not read yet" — the real query."""
        response = await client.get(
            f"/api/evaluation/runs/{seeded}/claims"
            "?label=UNSUPPORTED&unlabeled=true",
            headers=_headers(),
        )

        assert len(response.json()["items"]) == 1

    async def test_both_halves_at_once_is_refused(self, client, seeded):
        response = await client.get(
            f"/api/evaluation/runs/{seeded}/claims?labeled=true&unlabeled=true",
            headers=_headers(),
        )

        assert response.status_code == 422

    async def test_the_page_is_small_by_default(self, client, seeded):
        """
        Paged rather than whole. The header's total comes from `total`,
        so a small page no longer means a truncated screen.
        """
        import inspect

        from backend.api import claim_routes

        signature = inspect.signature(claim_routes.list_claims)

        assert signature.parameters["limit"].default.default == 25


class TestThePagedEnvelope:
    async def test_the_page_reports_the_total_it_came_from(
        self, client, seeded
    ):
        body = (
            await client.get(
                f"/api/evaluation/runs/{seeded}/claims?limit=1",
                headers=_headers(),
            )
        ).json()

        assert len(body["items"]) == 1
        assert body["total"] == 3

    async def test_offset_moves_the_window(self, client, seeded):
        first = (
            await client.get(
                f"/api/evaluation/runs/{seeded}/claims?limit=1",
                headers=_headers(),
            )
        ).json()["items"][0]

        second = (
            await client.get(
                f"/api/evaluation/runs/{seeded}/claims?limit=1&offset=1",
                headers=_headers(),
            )
        ).json()["items"][0]

        assert first["id"] != second["id"]

    async def test_the_total_follows_the_filter(self, client, seeded):
        """
        A filtered page must not advertise the unfiltered total, or Next
        pages through rows that are not there.
        """
        body = (
            await client.get(
                f"/api/evaluation/runs/{seeded}/claims?label=UNSUPPORTED",
                headers=_headers(),
            )
        ).json()

        assert body["total"] == 1

    async def test_paging_past_the_end_returns_an_empty_page(
        self, client, seeded
    ):
        body = (
            await client.get(
                f"/api/evaluation/runs/{seeded}/claims?offset=99",
                headers=_headers(),
            )
        ).json()

        assert body["items"] == []
        assert body["total"] == 3

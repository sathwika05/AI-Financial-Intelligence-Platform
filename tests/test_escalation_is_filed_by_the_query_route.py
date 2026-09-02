"""
The seam between withholding and filing.

The reviewer decides; the route persists. Nothing connects them except a
call in financial_routes, and that call is easy to lose in a refactor --
the endpoint would keep returning a correct, withheld response, the
analyst would keep seeing the notice, and the admin queue would silently
stay empty forever.

The graph is replaced here, not exercised: what is under test is whether
an escalated final_state reaches the queue, not whether the pipeline can
produce one. That question belongs to test_escalation_decision.
"""
import httpx
import pytest
from sqlalchemy import select

from backend.models.db_models import Escalation
from backend.services.postgres_service import AsyncSessionLocal


WITHHELD_DRAFT = {
    "query_summary": "Rank semiconductor companies by coverage",
    "intent": "SENTIMENT",
    "overall_confidence": 0.12,
    "companies": [{"ticker": "INTC", "confidence": 0.12}],
}

ESCALATED_STATE = {
    "draft_report": WITHHELD_DRAFT,
    "ranked_companies": [],
    "final_report": {
        "query_summary": "Rank semiconductor companies by coverage",
        "intent": "SENTIMENT",
        "top_companies": [],
        "withheld": True,
        "overall_confidence": 0.12,
        "review": {
            "escalated": True,
            "notice": "Confidence in this answer is 0.12, below the 0.30 floor.",
            "decision": "forced_pass",
            "flags": ["INTC: confidence 0.12 is below threshold 0.70"],
        },
    },
}

QUERY = "Which semiconductor company has the best recent coverage?"


@pytest.fixture
async def client(monkeypatch):
    """
    The API with the pipeline replaced by a fixed escalated result.

    httpx over ASGI rather than TestClient: TestClient drives the app from
    its own event loop in a worker thread, and the asyncpg pool these
    tests read the queue with belongs to this one. Sharing a connection
    across the two fails as "got result for unknown protocol state".
    """
    from backend.api import financial_routes
    from backend.llm.llm_config_service import LLMConfigService
    from backend.main import build_app

    async def fake_run(query, llm_runtime):
        return dict(ESCALATED_STATE)

    monkeypatch.setattr(financial_routes, "_run_financial_query", fake_run)

    class FakeRuntime:
        provider_name = "test-provider"
        models: dict = {}

    async def fake_default_runtime(self):
        return FakeRuntime()

    # Nothing here is about provider configuration, and loading it for
    # real needs a decryptable key in the local database.
    monkeypatch.setattr(
        LLMConfigService, "load_default_runtime", fake_default_runtime
    )

    app = build_app(deployment_mode="portfolio")

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    ) as session:
        yield session


@pytest.fixture(autouse=True)
async def clean():
    """Remove only the rows these tests create."""
    yield

    async with AsyncSessionLocal() as session:
        rows = (
            await session.execute(
                select(Escalation).where(Escalation.query == QUERY)
            )
        ).scalars().all()

        for row in rows:
            await session.delete(row)

        await session.commit()


async def _filed() -> list[Escalation]:
    async with AsyncSessionLocal() as session:
        return list(
            (
                await session.execute(
                    select(Escalation).where(Escalation.query == QUERY)
                )
            ).scalars().all()
        )


class TestAWithheldAnswerReachesTheQueue:
    async def test_a_row_is_filed(self, client):
        await client.post("/api/retrieve/financial", json={"query": QUERY})

        assert len(await _filed()) == 1

    async def test_the_row_holds_the_draft_the_analyst_never_saw(self, client):
        await client.post("/api/retrieve/financial", json={"query": QUERY})

        row = (await _filed())[0]

        assert row.withheld_report["companies"][0]["ticker"] == "INTC"

    async def test_the_response_carries_no_ranking(self, client):
        response = await client.post(
            "/api/retrieve/financial", json={"query": QUERY}
        )

        assert response.status_code == 200
        assert response.json()["final_report"]["top_companies"] == []

    async def test_the_response_explains_itself(self, client):
        response = await client.post(
            "/api/retrieve/financial", json={"query": QUERY}
        )

        assert response.json()["final_report"]["review"]["notice"]

    async def test_filing_failure_does_not_lose_the_response(
        self, client, monkeypatch
    ):
        """
        The queue is a side effect of answering, not part of it. A
        database that will not take the row must not turn a completed
        pipeline run into a 500 for the analyst.
        """
        from backend.api import financial_routes

        async def boom(*args, **kwargs):
            raise RuntimeError("queue is down")

        monkeypatch.setattr(financial_routes, "record_escalation", boom)

        response = await client.post(
            "/api/retrieve/financial", json={"query": QUERY}
        )

        assert response.status_code == 200

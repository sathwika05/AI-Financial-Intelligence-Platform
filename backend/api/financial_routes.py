

import json
import logging

from fastapi import APIRouter, Depends, HTTPException
from langchain_core.messages import HumanMessage
from langsmith import traceable
from pydantic import BaseModel, Field
from requests import session
from sqlalchemy.ext.asyncio import AsyncSession
from langchain_core.load import dumps

from backend.graph.financial_graph import financial_graph
from backend.llm.llm_config_service import LLMConfigService
from backend.observability.logging import query_run
from backend.services.postgres_service import get_db
from backend.state.state_factory import build_initial_financial_state
from backend.llm.usage_tracker import build_usage_config




class FinancialQueryRequest(BaseModel):
    query: str = Field(min_length=3, max_length=500)

logger = logging.getLogger(__name__)
router = APIRouter()

# Traced separately from the route handler: @traceable adds a `config`
# kwarg to the wrapped signature, which FastAPI would expose as a query
# parameter in the OpenAPI schema.
@traceable(
    name="api_financial_query",
    run_type="chain",
    tags=["api", "entrypoint"],
)
async def _run_financial_query(query: str, llm_runtime):
    """Invoke the financial graph as the root span of the trace."""
    initial_state = build_initial_financial_state(query)

    # The tracker rides on the config, so every nested LLM call is counted
    # without any node having to know about it.
    config, usage = build_usage_config(llm_runtime)

    final_state = await financial_graph.ainvoke(
        initial_state,
        config=config,
    )

    # Merged in rather than mutated into state: the graph has already
    # finished, and these are facts about the run, not part of it.
    return {**final_state, **usage.totals()}


@router.post("/api/retrieve/financial")
async def financial_retrieval(request: FinancialQueryRequest, session: AsyncSession = Depends(get_db),):
    """
    Unified hybrid retrieval endpoint.
    Flow:
    1. Intent classifier   ->  SQL / VECTOR / MIXED
    2. Query planner       -> decompose into subqueries
    3. Hybrid retrieval    -> SQL + Vector with MMR + BM25 + Market (parallel)
    4. Scoring   -> weighted multi-dimensional ranking
    5. Analysis -> LLM structured report 
    6. Reviewer -> hallucination check +retry 
    """
    """
    Regular financial request flow.

    1. Load the enabled default LLM provider.
    2. Load its configured models once.
    3. Build the request-scoped LLM runtime.
    4. Pass the runtime to LangGraph through config.
    5. Nodes reuse the same runtime without DB calls.
    """

    # Opened around the whole handler, error paths included, so every line
    # this request produces — here and in every node below it — is tagged
    # apart from a benchmark running concurrently in the background.
    with query_run():
        try:
            logger.info("[FINANCIAL_ROUTES] Query: %s", request.query,)

            llm_config_service = LLMConfigService(session)

            # UI does not send a provider for regular requests.
            # The backend loads the enabled default provider.
            llm_runtime = (
                await llm_config_service.load_default_runtime()
            )

            logger.info("[FINANCIAL_ROUTES] LLM runtime loaded: provider=%s, models=%s",
                        llm_runtime.provider_name,
                        llm_runtime.models,
                        )

            result = await _run_financial_query(
                request.query,
                llm_runtime,
            )
            print(json.dumps(json.loads(dumps(result)), indent=2))
            return {
                "query":  request.query,
                "provider": llm_runtime.provider_name,
                "final_report": result.get("final_report"),
                "ranked_companies": result.get("ranked_companies", []),
                "scoring_result": result.get("scoring_result"),
            }

        except RuntimeError as exc:
            logger.exception(
                "[FINANCIAL_ROUTES] LLM configuration failed"
            )

            raise HTTPException(
                status_code=503,
                detail=str(exc),
            ) from exc

        except Exception as exc:
            logger.exception(
                "[FINANCIAL_ROUTES] Retrieval failed"
            )

            raise HTTPException(
                status_code=500,
                detail="Retrieval failed. Please try again.",
            ) from exc


import logging

from fastapi import APIRouter, Depends, HTTPException
from langchain_core.messages import HumanMessage
from pydantic import BaseModel, Field
from requests import session
from sqlalchemy.ext.asyncio import AsyncSession

from backend.graph.financial_graph import financial_graph
from backend.llm.llm_config_service import LLMConfigService
from backend.services.postgres_service import get_db




class FinancialQueryRequest(BaseModel):
    query: str = Field(min_length=3, max_length=500)

logger = logging.getLogger(__name__)
router = APIRouter()

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
        
        initial_state = {
            "messages":       [HumanMessage(content=request.query)],
            "intent":         "",
            "original_query": request.query,
            "sql_query":      "",
            "vector_query":   "",
            "market_query": "",
            "strategy": "",
            "result": None,
            "market_result": None,
            "scoring_result": None,
            "ranked_companies": [],
            "draft_report": None,
            "review_report": None,
            "final_report": None,
            "should_retry":  False,
            "retry_count": 0,
        }

        result = await financial_graph.ainvoke(initial_state, config={"configurable":{"llm_runtime":llm_runtime}})

        return {
            "query":  request.query,
            "provider": llm_runtime.provider_name,
            "final_report": result.get("final_report"), 
            "result": result["result"]
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







import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.security import APIKeyHeader
from langchain_core.messages import HumanMessage
from pydantic import BaseModel, Field

from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import settings
from backend.graph.vector_graph import vector_graph
from backend.ingestion.indexing_service import embed_all_documents, embed_document
from backend.llm.llm_config_service import LLMConfigService
from backend.services.postgres_service import get_db


logger = logging.getLogger(__name__)
router = APIRouter(tags=["vector"])


# ── Admin auth ─────────────────────────────────────────────

API_KEY_HEADER = APIKeyHeader(name="X-Admin-Key")

def verify_admin(api_key: str=Depends(API_KEY_HEADER)):
    if api_key!= settings.ADMIN_API_KEY:
        raise HTTPException(
            status_code=403,
            detail="Unauthorized"
        )
    return api_key

# ── Request models ─────────────────────────────────────────

class QueryRequest(BaseModel):
    query: str = Field(min_length=3, max_length=500)
    top_k: int = Field(default=5, ge=1, le=20)

class IndexRequest(BaseModel):
    document_id: int | None = None

# ── Retrieval endpoint ─────────────────────────────────────

@router.post("/api/retrieve/vector")
async def vector_retrieval(
    request: QueryRequest,
    session: AsyncSession = Depends(get_db),
):
    """Semantic search over indexed document chunks."""
    try:
        logger.info(f"[VECTOR_ROUTES] Query: {request.query}")

        # vector_node is async and resolves its LLM from the runtime in
        # config, exactly like the financial route does.
        llm_runtime = await (
            LLMConfigService(session).load_default_runtime()
        )

        result = await vector_graph.ainvoke(
            {"messages": [HumanMessage(content=request.query)]},
            config={"configurable": {"llm_runtime": llm_runtime}},
        )
        return {
            "query": request.query,
            "answer": result["messages"][-1].content
        }
    except Exception as e:
        logger.error(f"[VECTOR_ROUTES] Retrieval failed: {e}")
        raise HTTPException(
            status_code=500,
            detail="Retrieval failed. Please try again."
        )
    



# ── Indexing endpoint (admin only) ─────────────────────────

@router.post("/api/index/documents")
async def index_documents(
    request: IndexRequest,
    background_tasks: BackgroundTasks,
    _: str = Depends(verify_admin)
):
    """Admin only — trigger document indexing."""
    if request.document_id:
        background_tasks.add_task(
            embed_document, request.document_id
        )
        return {
            "message": f"Indexing document "
                       f"{request.document_id} in background"
        }
    else:
        background_tasks.add_task(embed_all_documents)
        return {
            "message": "Indexing all documents in background"
        }
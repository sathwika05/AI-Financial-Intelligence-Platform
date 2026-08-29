






import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from langchain_core.messages import HumanMessage
from pydantic import BaseModel, Field

from sqlalchemy.ext.asyncio import AsyncSession

from backend.auth.dependencies import require_role
from backend.auth.roles import Role
from backend.config import settings
from backend.graph.vector_graph import vector_graph
from backend.ingestion.indexing_service import embed_all_documents, embed_document
from backend.llm.llm_config_service import LLMConfigService
from backend.services.postgres_service import get_db


logger = logging.getLogger(__name__)
router = APIRouter(tags=["vector"])


# Indexing is guarded by require_role(Role.ADMIN) on the route itself.
# A shared X-Admin-Key used to sit on top of it, which carried no identity,
# no expiry and no revocation -- and once ADMIN_API_KEY lost its published
# default, the header check refused the admin it existed to admit.

# ── Request models ─────────────────────────────────────────

class QueryRequest(BaseModel):
    query: str = Field(min_length=3, max_length=500)
    top_k: int = Field(default=5, ge=1, le=20)

class IndexRequest(BaseModel):
    document_id: int | None = None

# ── Retrieval endpoint ─────────────────────────────────────

@router.post(
    "/api/retrieve/vector",
    dependencies=[Depends(require_role(Role.ADMIN))],)
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

@router.post(
    "/api/index/documents",
    dependencies=[Depends(require_role(Role.ADMIN))],)
async def index_documents(
    request: IndexRequest,
    background_tasks: BackgroundTasks,
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
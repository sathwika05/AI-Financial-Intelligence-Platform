
import logging

from sqlalchemy import create_engine, text
from backend.services.postgres_service import engine

logger = logging.getLogger(__name__)




async def load_unindexed_documents()->list[dict]:
    """Load all documents that have no chunks yet."""
    try:
        async with engine.connect() as conn:
            result = await conn.execute(text(
                """
              SELECT d.id, d.content, d.doc_type,
                     d.source, d.company_id
              FROM documents d
              LEFT JOIN document_chunks dc
                   ON d.id = dc.document_id
              WHERE dc.id IS NULL
              AND d.content IS NOT NULL
              AND d.content != ''   
            """
            ))
            docs = [dict(row._mapping) for row in result.fetchall()]
            logger.info(f"[LOADER] Found {len(docs)} unindexed documents")
            return docs
    except Exception as e:
        logger.error(f"[LOADER] Failed to load documents: {e}")
        return []

async def load_document_by_id(document_id: int) -> dict | None:
    """Load a single document by id."""
    try:
        async with engine.connect() as conn:
            result = await conn.execute(text("""
                SELECT id, content, doc_type, source, company_id
                FROM documents
                WHERE id= :id                                              
             """),{"id": document_id})
            
            row = result.fetchone()
            return dict(row._mapping) if row else None
    except Exception as e:
        logger.error(f"[LOADER] Failed to load document {document_id}: {e}")
        return None
    

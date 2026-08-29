import asyncio
import logging

from langchain_openai import OpenAIEmbeddings
from tenacity import retry, stop_after_attempt, wait_exponential
from sqlalchemy import text

from backend.services.postgres_service import engine
from backend.ingestion.chunking import (
    SectionChunk,
    chunk_uid,
    chunk_with_sections,
)
from backend.ingestion.document_loader import (
    load_document_by_id,
    load_unindexed_documents,
)

logger = logging.getLogger(__name__)

embeddings = OpenAIEmbeddings(model="text-embedding-3-small")


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
)
async def embed_with_retry(chunks: list[str]) -> list[list[float]]:
    """Batch embed chunks with retry on failure."""
    return await embeddings.aembed_documents(chunks)


def to_pgvector(vector: list[float]) -> str:
    """Convert Python list[float] into pgvector string format."""
    return "[" + ",".join(str(x) for x in vector) + "]"


def chunk_rows(
    *,
    document_id: int,
    chunks: list[SectionChunk],
    vectors: list[list[float]],
) -> list[dict]:
    """
    The rows to write for one document.

    Split out from the insert so what gets stored can be checked without
    a database or an embedding call. A null chunk_uid is indistinguishable
    from a chunk written before the column existed, so getting this wrong
    is not visible later.
    """
    return [
        {
            "document_id": document_id,
            "chunk_index": index,
            "content": chunk.content,
            "embedding": to_pgvector(vector),
            "chunk_uid": chunk_uid(
                document_id=document_id,
                chunk_index=index,
                content=chunk.content,
            ),
            "section": chunk.section,
        }
        for index, (chunk, vector) in enumerate(zip(chunks, vectors))
    ]


async def embed_document(document_id: int) -> dict:
    """Embed a single document and store chunks in document_chunks."""

    doc = await load_document_by_id(document_id)

    if not doc:
        return {
            "success": False,
            "error": f"Document {document_id} not found",
        }

    chunks = chunk_with_sections(doc["content"])

    if not chunks:
        return {
            "success": False,
            "error": "No chunks generated",
        }

    try:
        vectors = await embed_with_retry([chunk.content for chunk in chunks])
        logger.info(f"[INDEXING] Embedded {len(chunks)} chunks for doc {document_id}")

    except Exception as e:
        logger.error(f"[INDEXING] Embedding failed for doc {document_id}: {e}")
        return {
            "success": False,
            "error": "Embedding API failed",
        }

    try:
        async with engine.begin() as conn:
            await conn.execute(
                text("""
                    DELETE FROM document_chunks
                    WHERE document_id = :document_id
                """),
                {"document_id": document_id},
            )

            for row in chunk_rows(
                document_id=document_id, chunks=chunks, vectors=vectors
            ):
                await conn.execute(
                    text("""
                        INSERT INTO document_chunks
                            (document_id, chunk_index, content, embedding,
                             chunk_uid, section)
                        VALUES
                            (:document_id, :chunk_index, :content,
                             CAST(:embedding AS vector), :chunk_uid, :section)
                    """),
                    row,
                )


        logger.info(f"[INDEXING] Stored {len(chunks)} chunks for doc {document_id}")

        return {
            "success": True,
            "chunks": len(chunks),
        }

    except Exception as e:
        logger.error(f"[INDEXING] DB insert failed for doc {document_id}: {e}")
        return {
            "success": False,
            "error": "Insert chunks failed",
        }


async def embed_all_documents() -> dict:
    """Index all unembedded documents."""

    docs = await load_unindexed_documents()

    if not docs:
        return {
            "message": "All documents already indexed",
            "total": 0,
        }

    success = 0
    failed = 0
    errors = []

    for doc in docs:
        result = await embed_document(doc["id"])

        if result["success"]:
            success += 1
        else:
            failed += 1
            errors.append({
                "document_id": doc["id"],
                "error": result["error"],
            })

        await asyncio.sleep(0.1)

    return {
        "message": "Indexing complete",
        "success": success,
        "failed": failed,
        "total": len(docs),
        "errors": errors,
    }
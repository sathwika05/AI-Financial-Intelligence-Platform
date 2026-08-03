import logging

from langchain_core.tools import tool
from langchain_openai import OpenAIEmbeddings
from sqlalchemy import text
from rank_bm25 import BM25Plus

from backend.services.postgres_service import engine

from backend.retrieval.query_filters import (
            extract_filters,
            generate_ranking_keywords
        )

logger = logging.getLogger(__name__)

embeddings = OpenAIEmbeddings(
    model="text-embedding-3-small"
)


async def search_similar_chunks_raw(query: str, top_k: int = 20, filters: dict = None) -> list:
    """
    Fetch top-k similar chunks using raw pgvector SQL.
    Applies metadata filters if provided.
    Fetches more than needed for BM25 to rerank.
    """

    query_embedding = embeddings.embed_query(query)

    vector_str = "[" + ",".join(
        str(x) for x in query_embedding
    ) + "]"

    filter_clauses = ["dc.embedding IS NOT NULL"]

    params = {
        "query_vector": vector_str,
        "top_k":        top_k
    }

    if filters:
        if "company_id" in filters:
            filter_clauses.append(
                "d.company_id = :company_id"
            )
            params["company_id"] = filters["company_id"]

        if "doc_type" in filters:
            filter_clauses.append(
                "d.doc_type = :doc_type"
            )
            params["doc_type"] = filters["doc_type"]

        if "source" in filters:
            filter_clauses.append(
                "d.source = :source"
            )
            params["source"] = filters["source"]

    where_clause = " AND ".join(filter_clauses)

    sql = text(f"""
        SELECT
            dc.content,
            dc.chunk_index,
            d.doc_type,
            d.source,
            d.company_id,
            1 - (dc.embedding <=> CAST(:query_vector AS vector))
                AS similarity
        FROM document_chunks dc
        JOIN documents d ON dc.document_id = d.id
        WHERE {where_clause}
        ORDER BY dc.embedding <=> CAST(:query_vector AS vector)
        LIMIT :top_k
    """)

    async with engine.connect() as conn:
        result = await conn.execute(sql, params)
        rows   = result.fetchall()

    logger.info(
        f"[VECTOR_SEARCH] pgvector returned {len(rows)} rows"
    )
    return rows    
    
# ── BM25 Reranker ──────────────────────────────────────────

def bm25_rerank(
     rows: list,
     keywords: list[str],
     top_k: int = 5   
) -> list:
    """
    Rerank retrieved rows using BM25Plus on financial keywords.

    pgvector fetches candidates by similarity
    BM25 reranks by keyword relevance
    Returns top_k most keyword-relevant rows
    """
    if not rows or not keywords:
        logger.warning(
            "[BM25] No rows or keywords — skipping rerank"
        )
        return rows[:top_k]
    
    query_tokens = " ".join(keywords).lower().split()

    doc_tokens = [
        row.content.lower().split() for row in rows
    ]

    bm25   = BM25Plus(doc_tokens)
    scores = bm25.get_scores(query_tokens)
    
    ranked = sorted(
        zip(rows, scores),
        key = lambda x: x[1],
        reverse = True
    )

    for rank, (row, score) in enumerate(ranked[:top_k],1):
        logger.info(
            f"[BM25] Rank {rank}: score={score:.4f} "
            f"chunk={row.chunk_index} "
            f"similarity={row.similarity:.3f}"
        )

    return [row for row, score in ranked[:top_k]]

# ── Full Pipeline ──────────────────────────────────────────

async def search_similar_chunks(
    query:    str,
    top_k:    int       = 5,
    filters:  dict      = None,
    keywords: list[str] = None
) -> list:
    """
    Full vector retrieval pipeline:

    Step 1 — pgvector cosine similarity
             fetch top_k * 4 candidates with metadata filters

    Step 2 — BM25 reranking
             rerank by keyword relevance
             return top_k results
    """
    fetch_k = top_k * 4

    logger.info(
        f"[VECTOR_SEARCH] Query: {query}, "
        f"filters: {filters}, "
        f"keywords: {keywords}, "
        f"fetch_k: {fetch_k}"
    )

    # Step 1 — pgvector similarity search
    rows = await search_similar_chunks_raw(
        query   = query,
        top_k   = fetch_k,
        filters = filters
    )

    if not rows:
        logger.warning("[VECTOR_SEARCH] No rows returned")
        return []

    # Step 2 — BM25 reranking
    reranked = bm25_rerank(rows, keywords or [], top_k)

    logger.info(
        f"[VECTOR_SEARCH] Final: {len(reranked)} chunks"
    )

    return reranked    


# ── LangGraph Tool ─────────────────────────────────────────


@tool
async def retrieve_similar(query: str, top_k: int = 5) -> str:
    """
    Retrieve top-k semantically similar document chunks
    using pgvector cosine similarity + BM25 reranking.
    Automatically extracts metadata filters and keywords.
    """

    try:

        logger.info(
            f"[VECTOR_SEARCH] Query: {query}, top_k: {top_k}"
        )

        filters  = await extract_filters(query)
        keywords = generate_ranking_keywords(query)


        rows = search_similar_chunks(
            query = query, 
            top_k = top_k,
            filters = filters,
            keywords= keywords)

        if not rows:
            return (
                "No relevant chunks found. "
                "Documents may not be indexed yet."
            )

        output = []

        for i, row in enumerate(rows, 1):

            output.append(
                f"""
            -------------- Result {i} ----------------------

            Company ID: {row.company_id}
            Type:       {row.doc_type}
            Source:     {row.source}
            Chunk:      {row.chunk_index}
            Similarity: {row.similarity:.3f}

            Content:
            {row.content[:600]}
            """
            )

        return "\n".join(output)

    except Exception as e:

        logger.error(f"[VECTOR_SEARCH] Failed: {e}")

        return (
            "Vector similarity search failed. "
            "Please try again."
        )
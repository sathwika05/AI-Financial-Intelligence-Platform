import logging

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from langchain_openai import OpenAIEmbeddings
from langsmith import traceable
from sqlalchemy import text
from rank_bm25 import BM25Plus

from backend.retrieval import cross_encoder, fusion, lexical_search
from backend.retrieval.embedding_cache import embed_query_cached
from backend.services.postgres_service import engine

from backend.retrieval.query_filters import (
            extract_filters,
            generate_ranking_keywords
        )

logger = logging.getLogger(__name__)

EMBEDDING_MODEL = "text-embedding-3-small"

embeddings = OpenAIEmbeddings(
    model=EMBEDDING_MODEL
)


# How many chunks each in-scope company should be able to contribute.
#
# The reranker applies the same idea to its evidence budget: a question
# covering N companies needs evidence for each of them, not N slots shared
# across the best-scoring one or two.
# Five, not three. This is the cap that binds: the reranker selects from
# what this returns, so raising its own evidence budget did nothing while
# this stayed at three.
#
# Recording the retrieved contexts (422500a) showed retrieval returning a
# median of about half the evidence the goldens themselves cite — mixed_002
# got 2 of its 17, and a three-company sentiment question could see nine
# chunks against the 14 its reference cites. Evidence that is never
# retrieved cannot support an answer however good the pipeline is.
#
# Not free: every chunk reaches the analysis prompt, and that node is the
# slowest stage in the graph. Measured by coverage — how many cited
# contexts appear in the retrieved set — rather than by context_recall,
# which moved 0.289 between two identical runs and would report noise.
CHUNKS_PER_COMPANY = 5


@traceable(
    name="pgvector_ann_search",
    run_type="retriever",
    tags=["retrieval", "vector", "db"],
)
async def search_similar_chunks_raw(query: str, top_k: int = 20, filters: dict = None) -> list:
    """
    Fetch top-k similar chunks using raw pgvector SQL.
    Applies metadata filters if provided.
    Fetches more than needed for BM25 to rerank.
    """

    query_embedding = await embed_query_cached(
        query,
        embedder=embeddings,
        model=EMBEDDING_MODEL,
    )

    vector_str = "[" + ",".join(
        str(x) for x in query_embedding
    ) + "]"

    filter_clauses = ["dc.embedding IS NOT NULL"]

    params = {
        "query_vector": vector_str,
        "top_k":        top_k
    }

    if filters:
        # company_ids is the multi-company form; company_id is still
        # accepted so single-company callers keep working.
        company_ids = filters.get("company_ids")

        if not company_ids and filters.get("company_id"):
            company_ids = [filters["company_id"]]

        if company_ids:
            filter_clauses.append(
                "d.company_id = ANY(:company_ids)"
            )
            params["company_ids"] = list(company_ids)

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
            dc.id,
            dc.document_id,
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

@traceable(
    name="bm25_rerank",
    run_type="chain",
    tags=["retrieval", "rerank", "lexical"],
)
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
    keywords: list[str] = None,
    rrf_enabled: bool = False,
    cross_encoder_enabled: bool = False,
) -> list:
    """
    Full vector retrieval pipeline.

    Step 1 — pgvector cosine similarity, fetching top_k * 4 candidates
             with metadata filters applied.

    Then one of two second stages, never both:

    Step 2  — BM25 reranking of what step 1 returned. The default, and
              what the demo serves. It can only reorder; it cannot
              surface anything dense retrieval missed.

    Step 2a — corpus-wide lexical ranking fused with the dense result by
              reciprocal rank fusion, when rrf_enabled. This replaces the
              rerank rather than following it, because once a list that
              can disagree is being fused in, reordering by the same
              signal adds nothing. Only evaluation_routes sets that flag,
              so this path is exercised by benchmarks and not by traffic.

    Step 3  — cross-encoder rerank, when cross_encoder_enabled. Off by
              default: it loads torch, roughly 270MB, which preprod's
              512MB instance cannot hold. Production could, and this is a
              per-run flag rather than a build-time one for that reason.

    Both flags arrive on config["configurable"]["retrieval_flags"], and
    absent means off, so any caller that does not set them gets steps 1
    and 2.
    """
    # Scale the result budget with the number of companies in scope.
    #
    # A fixed five is a per-question budget being spent on a per-company
    # job. sentiment_001 compares three companies and returned five chunks
    # from a cohort holding twelve, so a company could contribute nothing
    # and the comparison rested on whichever two happened to rank highest.
    # The question asks which company has the most positive coverage, and
    # that is unanswerable for a company with no retrieved coverage.
    #
    # Only widens, never narrows: an unfiltered query keeps the caller's
    # top_k.
    company_ids = (filters or {}).get("company_ids") or []

    if company_ids:
        top_k = max(
            top_k,
            CHUNKS_PER_COMPANY * len(company_ids),
        )

    fetch_k = top_k * 4

    logger.info(
        f"[VECTOR_SEARCH] Query: {query}, "
        f"filters: {filters}, "
        f"keywords: {keywords}, "
        f"companies: {len(company_ids)}, "
        f"top_k: {top_k}, "
        f"fetch_k: {fetch_k}"
    )

    # Step 1 — pgvector similarity search
    rows = await search_similar_chunks_raw(
        query   = query,
        top_k   = fetch_k,
        filters = filters
    )

    # A cross-encoder that only ever sees top_k has nothing to rerank, so
    # the stage feeding it keeps the wider pool and the cross-encoder makes
    # the final cut instead.
    shortlist_k = fetch_k if cross_encoder_enabled else top_k

    if rrf_enabled:
        # Step 2a — independent corpus-wide lexical ranking, fused by rank.
        #
        # This replaces the BM25 rerank rather than following it: that
        # stage only reorders what pgvector returned, so once a list that
        # can disagree is being fused in, reordering by the same signal
        # adds nothing.
        lexical_rows = await lexical_search.search_chunks_lexical(
            keywords = keywords or [],
            top_k    = fetch_k,
            filters  = filters,
        )

        fused = fusion.reciprocal_rank_fusion(
            [rows, lexical_rows],
            key=lambda row: row.id,
        )

        ranked = [result.item for result in fused][:shortlist_k]

        logger.info(
            "[VECTOR_SEARCH] rrf dense=%s lexical=%s fused=%s",
            len(rows),
            len(lexical_rows),
            len(fused),
        )
    else:
        if not rows:
            logger.warning("[VECTOR_SEARCH] No rows returned")
            return []

        # Step 2 — BM25 reranking
        ranked = bm25_rerank(rows, keywords or [], shortlist_k)

    if cross_encoder_enabled:
        # Step 3 — cross-encoder rerank. Fails open: a model that will not
        # load returns the ranking it was given.
        ranked = cross_encoder.rerank(
            query = query,
            rows  = ranked,
            top_k = top_k,
        )

    logger.info(
        f"[VECTOR_SEARCH] Final: {len(ranked)} chunks"
    )

    return ranked


# ── LangGraph Tool ─────────────────────────────────────────


@tool
async def retrieve_similar(
    query: str,
    config: RunnableConfig,
    top_k: int = 5,
) -> str:
    """
    Retrieve top-k semantically similar document chunks
    using pgvector cosine similarity + BM25 reranking.
    Automatically extracts metadata filters and keywords.
    """

    try:

        logger.info(
            f"[VECTOR_SEARCH] Query: {query}, top_k: {top_k}"
        )



        filters  = await extract_filters(query, config)
        keywords = await generate_ranking_keywords(query, config)

        # Per-run retrieval switches, carried on the same `configurable`
        # channel the nodes already read llm_runtime from. Absent means off,
        # so any caller that does not set them gets today's pipeline.
        flags = (
            (config.get("configurable") or {}).get("retrieval_flags")
            or {}
        )

        rows = await search_similar_chunks(
            query = query, 
            top_k = top_k,
            filters = filters,
            keywords= keywords,
            rrf_enabled=bool(flags.get("rrf_enabled")),
            cross_encoder_enabled=bool(
                flags.get("cross_encoder_enabled")
            ),
        )

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
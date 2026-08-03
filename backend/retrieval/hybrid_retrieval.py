import asyncio
from concurrent.futures import ThreadPoolExecutor
import logging

from langchain_core.messages import HumanMessage

from backend.graph.sql_graph import sql_graph
from backend.nodes.market_node import run_market_retrieval
from backend.retrieval.query_filters import (
    extract_filters,
    generate_ranking_keywords
)
from backend.retrieval.vector_search import search_similar_chunks

logger = logging.getLogger(__name__)

# controlled thread pool — tune max_workers based on load
executor = ThreadPoolExecutor(max_workers=6)

# timeouts per service
SQL_TIMEOUT    = 45  # seconds
VECTOR_TIMEOUT = 10  # seconds
MARKET_TIMEOUT = 8   # seconds


# ── Intent to retrieval path mapping ──────────────────────
SQL_INTENTS    = ["VALUATION", "GROWTH"]
VECTOR_INTENTS = ["SENTIMENT"]
MIXED_INTENTS  = ["MIXED"]


# ── SQL Retrieval ───────────────────────────────────────────

def run_sql_retrieval(query: str) -> dict:
    """
    Run SQL retrieval using the existing sql_graph.
    Returns structured results with confidence score.
    """
    try:
        result = sql_graph.invoke({
            "messages":          [HumanMessage(content=query)],
            "retry_count":       0,
            "original_question": query,
            "last_sql":          ""
        })

        answer     = result["messages"][-1].content
        confidence = 0.9 if "No companies" not in answer else 0.1

        logger.info("[HYBRID] SQL retrieval complete")
        return {
            "source":     "sql",
            "answer":     answer,
            "confidence": confidence
        }

    except Exception as e:
        logger.error(f"[HYBRID] SQL retrieval failed: {e}")
        return {
            "source":     "sql",
            "answer":     "",
            "confidence": 0.0,
            "error":      str(e)
        }


# ── Vector Retrieval ────────────────────────────────────────

async def run_vector_retrieval( query: str, top_k: int = 5) -> dict: 
    """
    Run vector retrieval pipeline:
    1. Extract metadata filters from query
    2. Generate ranking keywords from query
    3. pgvector cosine similarity search with filters
    4. BM25 reranking by keyword relevance
    Returns structured result with confidence score.
    """
    try:
        filters  = await extract_filters(query)
        keywords = generate_ranking_keywords(query)

        logger.info(
            f"[VECTOR] Vector filters: {filters}, "
            f"keywords: {keywords}"
        )

        rows = await search_similar_chunks(
            query    = query,
            top_k    = top_k,
            filters  = filters,
            keywords = keywords
        )

        if not rows:
            return {
                "source":     "vector",
                "chunks":     [],
                "confidence": 0.0
            }

        chunks = [{
            "content":     row.content[:600],
            "doc_type":    row.doc_type,
            "source":      row.source,
            "company_id":  row.company_id,
            "chunk_index": row.chunk_index,
            "similarity":  round(row.similarity, 3)
        } for row in rows]

        confidence = 0.8 if chunks else 0.0

        logger.info(
            f"[HYBRID] Vector complete. "
            f"{len(chunks)} chunks found"
        )

        return {
            "source":     "vector",
            "chunks":     chunks,
            "confidence": confidence
        }

    except Exception as e:
        logger.error(f"[HYBRID] Vector retrieval failed: {e}")
        return {
            "source":     "vector",
            "chunks":     [],
            "confidence": 0.0,
            "error":      str(e)
        }

# ── Async Wrappers with Timeouts ────────────────────────────

async def run_sql_retrieval_async(query: str) -> dict:
    """Async SQL retrieval with timeout."""
    loop= asyncio.get_event_loop()
    try:
        logger.info("[HYBRID] SQL task started")
        
        result = await asyncio.wait_for(
            loop.run_in_executor(
                executor,
                run_sql_retrieval,
                query
            ),
            timeout=SQL_TIMEOUT
        )
        
        #result = run_sql_retrieval(query)
        logger.info("[HYBRID] SQL task complete")
        return result
    except asyncio.TimeoutError:
        logger.error(f"[HYBRID] SQL timed out after {SQL_TIMEOUT}s")
        return {
            "source": "sql",
            "answer": "",
            "confidence": 0.0,
            "error": "timeout"
        }
    except Exception as e:
        logger.error(f"[HYBRID] SQL async failed: {e}", exc_info=True)
        return {
            "source": "sql",
            "answer": "",
            "confidence": 0.0,
            "error": str(e)
        }
    

async def run_vector_retrieval_async(query: str) -> dict:
    """Async vector retrieval with timeout."""
    loop = asyncio.get_event_loop()
    try:
        logger.info("[HYBRID] Vector task started")
        
        result = await asyncio.wait_for(
             run_vector_retrieval(query),
            timeout=VECTOR_TIMEOUT
        )
        
        #result = run_vector_retrieval(query)
        logger.info("[HYBRID] Vector task complete")
        return result
    except asyncio.TimeoutError:
        logger.error(f"[HYBRID] Vector timed out after {VECTOR_TIMEOUT}s")
        return {
            "source":     "vector",
            "chunks":     [],
            "confidence": 0.0,
            "error":      "timeout"
        }
    except Exception as e:
        logger.error(f"[HYBRID] Vector async failed: {e}", exc_info=True)
        return {
            "source":     "vector",
            "chunks":     [],
            "confidence": 0.0,
            "error":      str(e)
        }


async def run_market_retrieval_async(market_query: str) -> dict:
    """Async market retrieval with timeout."""
    loop = asyncio.get_event_loop()
    try:
        logger.info("[HYBRID] Market task started")
        
        result = await asyncio.wait_for(
            loop.run_in_executor(
                executor,
                run_market_retrieval,
                market_query
            ),
            timeout=MARKET_TIMEOUT
        )
        
        #result = run_market_retrieval(market_query)
        logger.info("[HYBRID] Market task complete")
        return result
    except asyncio.TimeoutError:
        logger.error(f"[HYBRID] Market timed out after {MARKET_TIMEOUT}s")
        return {
            "source":     "market",
            "data":       {},
            "confidence": 0.0,
            "error":      "timeout"
        }
    except Exception as e:
        logger.error(f"[HYBRID] Market async failed: {e}", exc_info=True)
        return {
            "source":     "market",
            "data":       {},
            "confidence": 0.0,
            "error":      str(e)
        }

# ── Dynamic Weight Calculator ───────────────────────────────

def calculate_weights(
    intent:        str,
    market_result: dict = None
) -> dict:
    """
    Calculate confidence weights dynamically.
    Adjusts market weight to 0 if market data unavailable.
    Redistributes weight to SQL and Vector.
    """
    market_available = (
        market_result is not None and
        market_result.get("confidence", 0.0) > 0
    )

    if intent in SQL_INTENTS:
        return {"sql": 1.0, "vector": 0.0, "market": 0.0}

    elif intent in VECTOR_INTENTS:
        return {"sql": 0.0, "vector": 1.0, "market": 0.0}

    else:  # MIXED
        if market_available:
            return {"sql": 0.4, "vector": 0.3, "market": 0.3}
        else:
            # market unavailable — redistribute its weight
            return {"sql": 0.6, "vector": 0.4, "market": 0.0}





# ── Combine Results ─────────────────────────────────────────

def combine_results(
    query:         str,
    intent:        str,
    sql_result:    dict = None,
    vector_result: dict = None,
    market_result: dict = None
) -> dict:
    """
    Combine retrieval results into unified response.
    Adjusts weights when market data unavailable.
    Weights per intent:
    VALUATION → SQL 100%
    GROWTH    → SQL 100%
    SENTIMENT → Vector 100%
    MIXED     → SQL 40% + Vector 30% + Market 30%
    """

    sql_r    = sql_result    or {"confidence": 0.0}
    vector_r = vector_result or {"confidence": 0.0}
    market_r = market_result or {"confidence": 0.0}

    weights = calculate_weights(intent, market_result)

    overall_confidence = round(
        (sql_r["confidence"]    * weights["sql"])    +
        (vector_r["confidence"] * weights["vector"]) +
        (market_r["confidence"] * weights["market"]),
        3
    )

    result = {
        "query":              query,
        "intent":             intent,
        "overall_confidence": overall_confidence,
        "weights_used":       weights
    }

    if sql_result:
        result["sql_result"] = {
            "answer":     sql_result["answer"],
            "confidence": sql_result["confidence"],
            "error":      sql_result.get("error")
        }

    if vector_result:
        result["vector_result"] = {
            "chunks":     vector_result["chunks"],
            "confidence": vector_result["confidence"],
            "error":      vector_result.get("error")
        }

    if market_result:
        result["market_result"] = {
            "data":       market_result["data"],
            "confidence": market_result["confidence"],
            "cached":     market_result.get("cached", False),
            "error":      market_result.get("error")
        }

    
    return result




# ── Main Async Hybrid Function ────────────────────────────────────

async def hybrid_retrieve_async(
    query:        str,
    intent:       str,
    sql_query:    str = None,
    vector_query: str = None,
    market_query: str = None
) -> dict:
    """
    Production-grade async hybrid retrieval.

    Features:
    - Fan-out/fan-in with asyncio.gather
    - Per-service timeouts
    - Partial results on failure
    - Dynamic weight adjustment
    - Full exception logging

    Routes:
    VALUATION → SQL only
    GROWTH    → SQL only
    SENTIMENT → Vector only
    MIXED     → SQL + Vector + Market in parallel
    """
    sql_q    = sql_query    or query
    vector_q = vector_query or query
    market_q = market_query or ""

    logger.info(
        f"[HYBRID] Intent: {intent}, "
        f"sql_q: {sql_q[:50]}, "
        f"vector_q: {vector_q[:50]}, "
        f"market_q: {market_q[:50]}"
    )

    if intent in SQL_INTENTS:
        # VALUATION or GROWTH → SQL only
        sql_result = run_sql_retrieval(sql_q)
        return combine_results(
            query      = query,
            intent     = intent,
            sql_result = sql_result
        )

    elif intent in VECTOR_INTENTS:
        # SENTIMENT → Vector only
        vector_result = await run_vector_retrieval(vector_q)
        return combine_results(
            query         = query,
            intent        = intent,
            vector_result = vector_result
        )

    else:
        # MIXED → SQL + Vector + Market API
        # MIXED — fan-out all tasks in parallel with timeout
        logger.info(
            "[HYBRID_ASYNC] Fanning out 3 tasks in parallel"
        )

        tasks = [
            run_sql_retrieval_async(sql_q),
            run_vector_retrieval_async(vector_q),
        ]

        if market_q:
            tasks.append(run_market_retrieval_async(market_q))

        try:
            # fan-in with overall timeout
            
            results = await asyncio.wait_for(
                asyncio.gather(*tasks, return_exceptions=True),
                timeout=60
            ) 
            
            #sql_result = await run_sql_retrieval_async(sql_q)
            #vector_result = await run_vector_retrieval_async(vector_q)
            #market_result = await run_market_retrieval_async(market_q)
        except asyncio.TimeoutError:
            logger.error("[HYBRID_ASYNC] Overall timeout after 20s")
            results = [
                {"source": "sql",    "answer": "", "confidence": 0.0, "error": "timeout"},
                {"source": "vector", "chunks": [], "confidence": 0.0, "error": "timeout"},
            ]
        

        # extract results safely
        sql_result = results[0] if (
            len(results) > 0 and
            not isinstance(results[0], Exception)
        ) else {"source": "sql", "answer": "", "confidence": 0.0, "error": "failed"}

        vector_result = results[1] if (
            len(results) > 1 and
            not isinstance(results[1], Exception)
        ) else {"source": "vector", "chunks": [], "confidence": 0.0, "error": "failed"}

        market_result = results[2] if (
            len(results) > 2 and
            not isinstance(results[2], Exception)
        ) else None

        # log exceptions
        for i, r in enumerate(results):
            if isinstance(r, Exception):
                logger.error(
                    f"[HYBRID_ASYNC] Task {i} raised: {r}",
                    exc_info=r
                )

        logger.info(
            f"[HYBRID_ASYNC] Fan-in complete. "
            f"SQL: {sql_result.get('confidence', 0)}, "
            f"Vector: {vector_result.get('confidence', 0)}, "
            f"Market: {market_result.get('confidence', 0) if market_result else 'N/A'}"
        )

        return combine_results(
            query         = query,
            intent        = intent,
            sql_result    = sql_result,
            vector_result = vector_result,
            market_result = market_result
        )
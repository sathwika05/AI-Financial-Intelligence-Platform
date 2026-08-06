





import asyncio
import logging
import operator
from typing import Annotated, Any, Optional, TypedDict

from langchain_core.messages import BaseMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph, add_messages

from backend.nodes.analysis_node import analysis_node
from backend.nodes.intent_node import intent_node
from backend.nodes.planner_node import planner_node
from backend.nodes.reviewer_node import reviewer_node, route_after_review
from backend.nodes.scoring_node import scoring_node
from backend.retrieval.hybrid_retrieval import hybrid_retrieve_async
from backend.state.financial_state import FinancialState


logger = logging.getLogger(__name__)






# ── Retrieval Node ──────────────────────────────────────────

async def retrieval_node(state: FinancialState, config: RunnableConfig) -> dict:
    """
    Runs async parallel hybrid retrieval.
    Uses asyncio.run to execute async function
    from sync LangGraph node context.

    Production note: ideally LangGraph node would be
    natively async, but current LangGraph version
    requires sync nodes. asyncio.run is safe here
    as each node runs in its own execution context.
    """    

    intent       = state["intent"]
    sql_query    = state.get("sql_query",    state["original_query"])
    vector_query = state.get("vector_query", state["original_query"])
    market_query = state.get("market_query", "")

    logger.info(
        f"[FINANCIAL_GRAPH] Async parallel retrieval. "
        f"Intent: {intent}"
    )

    result = await hybrid_retrieve_async(
            query        = state["original_query"],
            intent       = intent,
            sql_query    = sql_query,
            vector_query = vector_query,
            market_query = market_query,
            config       = config
    )

    # Spread into the keys FinancialState declares. LangGraph drops any
    # key that is not in the state schema, so a nested "result" blob
    # would silently vanish before the scoring node runs.
    vector_result = result.get("vector_result", {})

    return {
        **state,
        "sql_result":         result.get("sql_result", {}),
        "vector_result":      vector_result,
        "market_result":      result.get("market_result", {}),
        "retrieved_contexts": vector_result.get(
            "retrieved_contexts", []
        ),
    }


# ── Routers ─────────────────────────────────────────────────

def route_after_intent(state: FinancialState) -> str:
    return "planner"


def route_after_planner(state: FinancialState) -> str:
    return "retrieval"

# ── Graph ───────────────────────────────────────────────────

def build_financial_graph():
    graph = StateGraph(FinancialState)

    graph.add_node("intent",    intent_node)
    graph.add_node("planner",   planner_node)
    graph.add_node("retrieval", retrieval_node)
    graph.add_node("scoring",   scoring_node) 
    graph.add_node("analysis", analysis_node)
    graph.add_node("reviewer",reviewer_node)


    graph.add_edge(START, "intent")
    graph.add_conditional_edges(
        "intent",
        route_after_intent,
        {"planner": "planner"}
    )
    graph.add_conditional_edges(
       "planner",
       route_after_planner,
       {"retrieval": "retrieval"}
   )

    graph.add_edge("retrieval", "scoring") 
    graph.add_edge("scoring",   "analysis")
    graph.add_edge("analysis","reviewer") 

    graph.add_conditional_edges(
        "reviewer",
        route_after_review,
        {
            "retrieval": "retrieval",  # retry → back to retrieval
            "output":    END,          # approved → done
        }
    )
    
    logger.info("[FINANCIAL_GRAPH] Graph compiled")
    return graph.compile()


financial_graph = build_financial_graph()
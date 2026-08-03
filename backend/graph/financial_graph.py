





import asyncio
import logging
import operator
from typing import Annotated, Any, Optional, TypedDict

from langgraph.graph import END, START, StateGraph

from backend.nodes.analysis_node import analysis_node
from backend.nodes.intent_node import intent_node
from backend.nodes.planner_node import planner_node
from backend.nodes.reviewer_node import reviewer_node, route_after_review
from backend.nodes.scoring_node import scoring_node
from backend.retrieval.hybrid_retrieval import hybrid_retrieve_async


logger = logging.getLogger(__name__)

# ── State ───────────────────────────────────────────────────

class FinancialState(TypedDict):
    messages: Annotated[list, operator.add]
    original_query: str

    intent:   str
    intent_reason: str
    
    sql_query: str
    vector_query: str
    market_query: str
    strategy: str

    sql_result: dict[str, Any]
    vector_result: dict[str, Any]
    market_result: dict[str, Any]

    retrieved_contexts: list[str]
    reranked_contexts: list[str]

    scoring_result: Optional[dict]   # ← added
    ranked_companies: list

    draft_report: Optional[dict] # from analysis_node
    review_result: Optional[dict] # from reviewer_node
    final_report: Optional[dict] # approved output

    should_retry: bool # reviewer retry flag
    retry_count: int # retry counter

    executed_tools: Annotated[list[str], operator.add,]



# ── Retrieval Node ──────────────────────────────────────────

async def retrieval_node(state: FinancialState) -> dict:
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
            market_query = market_query
    )

    return {**state, "result": result}


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
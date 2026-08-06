import logging

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel, Field
from backend.llm.llm_context import get_llm_client
from backend.llm.llm_tiers import LLMTier

logger = logging.getLogger(__name__)



class QueryIntent(BaseModel):
    """
    Structured output returned by the intent-classification
    Large Language Model.
    """

    intent: str = Field(
        description="Query intent: VALUATION, GROWTH, SENTIMENT or MIXED"
    )
    reason: str = Field(
        description="Brief reason for the classification"
    )

# System instructions are stored as plain text.
# A SystemMessage is created only when invoking the model.
INTENT_SYSTEM_PROMPT = """
You are a financial query classifier.

Classify the user query into exactly one of:

VALUATION
    - Questions about stock-price metrics and value
    - Price-to-Earnings ratio, market capitalization,
      undervalued, overvalued, or fair value
    - Price-based filtering and ranking
    - Examples:
        "Find undervalued technology companies"
        "Which stocks have a low Price-to-Earnings ratio?"
        "Show me large-capitalization companies"

GROWTH
    - Questions about business performance and expansion
    - Revenue growth, Earnings Per Share, earnings,
      and profit margins
    - Growth-based filtering and ranking
    - Examples:
        "Show companies with revenue growth over 20%"
        "Which companies have strong Earnings Per Share?"
        "Find high-growth technology stocks"

SENTIMENT
    - Questions about news, opinions, or commentary
    - Earnings-call content, Securities and Exchange
      Commission filings, and news articles
    - Management statements, analyst opinions,
      and market sentiment
    - Examples:
        "What did Apple say about Artificial Intelligence?"
        "Show positive news about NVIDIA"
        "What are analysts saying about Tesla?"
        "What did management say about the growth outlook?"

MIXED
    - Questions requiring both structured metrics
      and document context
    - Combines valuation or growth with sentiment
    - Examples:
        "Find undervalued Artificial Intelligence companies
         with positive news"
        "Cheap technology stocks with good earnings commentary"
        "Low Price-to-Earnings companies with a strong
         growth narrative"
        "Which high-growth companies have positive sentiment?"

Return:
- intent: exactly one of VALUATION, GROWTH, SENTIMENT, MIXED
- reason: a short explanation for the classification
""".strip()

async def classify_intent(query: str, config: RunnableConfig) -> QueryIntent:
    """
    Classify query into business domain intent.

    VALUATION  → PE ratio, undervalued, market cap, price metrics
    GROWTH     → revenue growth, EPS, expansion, earnings
    SENTIMENT  → news, opinions, earnings calls, filings, commentary
    MIXED      → combination of metrics AND document context
    """
    llm = get_llm_client(config, LLMTier.SMALL)
    llm_structured = llm.with_structured_output(QueryIntent)

    
    # Pass RunnableConfig downstream so tags, metadata,
    # and LangSmith tracing remain attached to this call.
    response = await llm_structured.ainvoke([
        SystemMessage(
                content=INTENT_SYSTEM_PROMPT
            ),
        HumanMessage(content=query)
        ],
        config=config,
    )

    intent = response.intent.upper().strip()
    if intent not in ["VALUATION", "GROWTH", "SENTIMENT", "MIXED"]:
        logger.warning(
            "[INTENT] Unsupported intent '%s'; "
            "falling back to MIXED",
            intent,
        )
        intent = "MIXED"

    result = QueryIntent(
        intent=intent,
        reason=response.reason.strip(),
    )

    logger.info(
        "[INTENT] Query='%s' intent=%s reason=%s",
        query,
        result.intent,
        result.reason,
    )

    return result


async def intent_node(state: dict,config: RunnableConfig) -> dict:
    """LangGraph node that classifies query intent."""
    query  = state["messages"][-1].content
    # Compatibility fallback for states created before
    # original_query was initialized.
    if not query:
        messages = state.get(
            "messages",
            [],
        )

        if not messages:
            raise ValueError(
                "Intent node received no original query "
                "and no messages."
            )

        query = str(
            messages[0].content
        )

    classification = await classify_intent(
        query=query,
        config=config,
    )

    return {
         "intent": classification.intent,
         "intent_reason": classification.reason,
         "original_query": query,
    }

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
        description=(
            "Query intent: VALUATION, GROWTH, SENTIMENT, MIXED "
            "or OUT_OF_SCOPE"
        )
    )
    reason: str = Field(
        description="Brief reason for the classification"
    )


# The fifth classification, and the one the schema was missing.
#
# A live "hello" was classified SENTIMENT with the reason "User greeted; no
# financial query provided" — the model diagnosed it correctly and had
# nowhere to put the diagnosis, because the contract demanded one of four
# financial intents. It then ranked the whole corpus by revenue growth.
OUT_OF_SCOPE = "OUT_OF_SCOPE"

_VALID_INTENTS = [
    "VALUATION",
    "GROWTH",
    "SENTIMENT",
    "MIXED",
    OUT_OF_SCOPE,
]


def build_out_of_scope_report(reason: str) -> dict:
    """
    The whole answer for a question the system will not attempt.

    Deliberately not the withheld shape. Withheld means the pipeline ran
    and the result was not trusted, and it tells the reader the evidence
    was too thin — which would be the wrong explanation here, because
    nothing was retrieved and there is nothing wrong with the corpus.
    """
    return {
        "query_summary": None,
        "intent": OUT_OF_SCOPE,
        "top_companies": [],
        "out_of_scope": True,
        "overall_confidence": None,
        "evidence_quality": None,
        "review": {
            "escalated": False,
            "decision": OUT_OF_SCOPE,
            "reason": reason,
            "notice": (
                "That does not look like a research question. Try naming a "
                "company, a sector, or a metric — for example “healthcare "
                "companies with the strongest revenue growth”."
            ),
            "flags": [],
            "total_flags": 0,
            "hallucination_rate": 0.0,
        },
        "sources_used": {},
    }

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

    - NOT two structured metrics together. A question that filters on one
      number and ranks on another is answered entirely in SQL, and needs
      no documents. Combining pe_ratio with revenue_growth does not make a
      question MIXED; asking what people SAY about a company does.
    - Counter-examples, all single-intent:
        "Among companies trading below a P/E ratio of 30, which five have
         the strongest revenue growth?"                        -> GROWTH
        "Which profitable companies have the smallest market
         capitalisation?"                                      -> VALUATION
    - The test is what the answer needs, not how many measures the
      question names. If every clause maps to a column, it is not MIXED.

OUT_OF_SCOPE
    - Not a research question at all: a greeting, small talk, a question
      about this tool, or anything naming no company, sector, metric or
      financial topic.
        "hello"                                             -> OUT_OF_SCOPE
        "what can you do?"                                  -> OUT_OF_SCOPE
        "thanks!"                                           -> OUT_OF_SCOPE
    - A bare company name is IN scope, not out of it. "microsoft" is a
      terse question about Microsoft, and answering it is correct.
        "microsoft"                                              -> SENTIMENT
        "AMD vs NVDA"                                                -> MIXED
    - When unsure, choose a financial intent. Refusing a real question is
      a worse failure than answering a vague one, so this is for input
      with no financial content whatsoever — not for input that is merely
      short, awkward or ambiguous.

Return:
- intent: exactly one of VALUATION, GROWTH, SENTIMENT, MIXED, OUT_OF_SCOPE
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
    if intent not in _VALID_INTENTS:
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

    result = {
        "intent": classification.intent,
        "intent_reason": classification.reason,
        "original_query": query,
    }

    # Answer here rather than routing five more stages to discover the
    # same thing. The reviewer would now withhold this report, which is
    # the right terminal reached the wrong way: six LLM calls and roughly
    # two minutes to decline a greeting, and a notice blaming thin
    # evidence for a question that named nothing to find evidence about.
    if classification.intent == OUT_OF_SCOPE:
        result["final_report"] = build_out_of_scope_report(
            classification.reason
        )

    return result

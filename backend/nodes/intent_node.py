import logging

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field


logger = logging.getLogger(__name__)

llm = ChatOpenAI(model="gpt-5.4-nano", temperature=0)


class QueryIntent(BaseModel):
    intent: str = Field(
        description="Query intent: VALUATION, GROWTH, SENTIMENT or MIXED"
    )
    reason: str = Field(
        description="Brief reason for the classification"
    )


def classify_intent(query: str) -> str:
    """
    Classify query into business domain intent.

    VALUATION  → PE ratio, undervalued, market cap, price metrics
    GROWTH     → revenue growth, EPS, expansion, earnings
    SENTIMENT  → news, opinions, earnings calls, filings, commentary
    MIXED      → combination of metrics AND document context
    """
    llm_structured = llm.with_structured_output(QueryIntent)

    system = SystemMessage(content="""
            You are a financial query classifier.

                Classify the user query into exactly one of:

            VALUATION
                - Questions about stock price metrics and value
                - PE ratio, market cap, undervalued, overvalued, fair value
                - Price-based filtering and ranking
                - Examples:
                        "Find undervalued tech companies"
                        "Which stocks have low PE ratio?"
                        "Show me large cap companies"

            GROWTH
                - Questions about business performance and expansion
                - Revenue growth, EPS, earnings, profit margins
                - Growth-based filtering and ranking
                - Examples:
                        "Show companies with revenue growth over 20%"
                        "Which companies have strong EPS?"
                        "Find high growth technology stocks"

            SENTIMENT
                - Questions about news, opinions, commentary
                - Earnings call content, SEC filings, news articles
                - What companies said, analyst opinions, market sentiment
                - Examples:
                        "What did Apple say about AI?"
                        "Show positive news about NVIDIA"
                        "What are analysts saying about Tesla?"
                        "What did management say about growth outlook?"

            MIXED
                - Questions needing BOTH metrics AND documents
                - Combining valuation/growth with sentiment
                - Examples:
                        "Find undervalued AI companies with positive news"
                        "Cheap tech stocks with good earnings commentary"
                        "Low PE companies with strong growth narrative"
                        "Which high growth companies have positive sentiment?"

            Return only VALUATION, GROWTH, SENTIMENT or MIXED.
        """)

    response = llm_structured.invoke([
        system,
        HumanMessage(content=query)
    ])

    intent = response.intent.upper().strip()
    if intent not in ["VALUATION", "GROWTH", "SENTIMENT", "MIXED"]:
        intent = "MIXED"

    logger.info(
        f"[INTENT] Query: '{query}' → {intent} ({response.reason})"
    )

    return intent


def intent_node(state: dict) -> dict:
    """LangGraph node that classifies query intent."""
    query  = state["messages"][-1].content
    intent = classify_intent(query)
    return {
        **state,
        "intent":         intent,
        "original_query": query
    }
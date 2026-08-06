import logging

from langchain_core.messages import SystemMessage
from langchain_core.runnables import RunnableConfig
from langgraph.prebuilt import ToolNode

from backend.llm.llm_context import get_llm_client
from backend.llm.llm_tiers import LLMTier
from backend.retrieval.vector_search import retrieve_similar


logger = logging.getLogger(__name__)

VECTOR_TOOLS = [retrieve_similar]


async def vector_node(
    state: dict,
    config: RunnableConfig,
) -> dict:
    """
    LangGraph node for semantic document retrieval.

    This node retrieves existing indexed documents.
    It does not create embeddings or index documents.
    """
    messages = state.get("messages", [])

    if not messages:
        raise ValueError(
            "Vector node requires at least one message."
        )

    llm = get_llm_client(
        config,
        LLMTier.MEDIUM,
    )

    llm_with_tools = llm.bind_tools(
        VECTOR_TOOLS
    )

    system_message = SystemMessage(
        content="""
You are a financial document semantic-search specialist.

Your only available tool is retrieve_similar.

The tool searches:
- Earnings-call transcripts
- SEC filings such as 10-K and 10-Q reports
- Financial news articles

Instructions:
- Always call retrieve_similar using the user's question.
- Do not answer from your own knowledge.
- Base the response only on retrieved documents.
- Preserve company name, document type, similarity score, and relevant content.
- Do not invent missing document details.
""".strip()
    )

    response = await llm_with_tools.ainvoke(
        [
            system_message,
            *messages,
        ],
        config=config,
    )

    logger.info(
        "[VECTOR_NODE] Response generated; tool_calls=%s",
        len(getattr(response, "tool_calls", []) or []),
    )

    return {
        "messages": [response],
    }


vector_tool_node = ToolNode(
    VECTOR_TOOLS
)
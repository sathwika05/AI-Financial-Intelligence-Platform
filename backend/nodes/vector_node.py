



import logging

from langchain_core.messages import SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import ToolNode

from backend.retrieval.vector_search import retrieve_similar


logger = logging.getLogger(__name__)

llm = ChatOpenAI(model="gpt-5.4-mini",temperature=0)
tools = [retrieve_similar]
llm_with_tools = llm.bind_tools(tools)

def vector_node(state: dict) -> dict:
    """
    LanGraph node for semantic document retrieval
    Only retrieves - never indexes
    """

    system = SystemMessage(content = """
     You are a financial document semantic search specialist.
                           
      Your only tool is retrieve_similar which searches:
        - Earnings call transcripts
        - SEC filings (10-K, 10-Q)
        - Financial news articles  
      Always call retrieve_similar with the user question.
      Return results with company name, document type,
      similarity score and relevant content.                                                          
    """
    )
    messages = [system] + state["messages"]
    response = llm_with_tools.invoke(messages)
    logger.info("[VECTOR_NODE] Response generated")
    return {"messages":[response]}

vector_tool_node = ToolNode(tools)

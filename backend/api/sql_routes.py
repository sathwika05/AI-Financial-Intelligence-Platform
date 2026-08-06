


from fastapi import APIRouter
from langchain_core.messages import HumanMessage
from pydantic import BaseModel

from backend.graph.sql_graph import sql_graph


class QueryRequest(BaseModel):
    query: str


router = APIRouter()


@router.post("/api/retrieve/sql")
async def retrieve_sql(request: QueryRequest):
    result = await sql_graph.ainvoke({
       'messages': [HumanMessage(content=request.query)],
       'retry_count': 0,
       'original_question': '',
       'last_sql': '',
       'db_result': {},
       'sql_executed_tools': []
    })

    #last message is the final agent response
    last_message = result['messages'][-1]
    return {"answer": last_message.content}

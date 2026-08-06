import logging

from langsmith import traceable


logger = logging.getLogger(__name__)






@traceable(
    name="attach_company_evidence",
    run_type="chain",
    tags=["scoring", "evidence"],
)
def attach_company_evidence(company: dict,
    sql_result: dict | None = None,
    vector_result: dict | None = None,
    market_result: dict | None = None) -> list[dict]:

    ticker = company.get("ticker", "").upper()
    name = company.get("name", "").lower()

    evidence = []

    # SQL evidence
    if sql_result and sql_result.get("rows"):
        for i, row in enumerate(sql_result["rows"]):
            text = str(row)

            if ticker in text.upper() or name in text.lower():
                evidence.append({
                    "citation_id": f"{ticker}-sql-{i+1}",
                    "source": "sql",
                    "text": text,
                    "supports": "valuation/growth metrics"
                })
            
            # Vector/news/document evidence
    if vector_result and vector_result.get("retrieved_chunks"):
        for i, chunk in enumerate(vector_result["retrieved_chunks"]):
            text = chunk.get("content", "")

            if ticker in text.upper() or name in text.lower():
                evidence.append({
                    "citation_id": f"{ticker}-vector-{i+1}",
                    "source": "vector",
                    "text": text[:500],
                    "supports": "sentiment/document evidence"
                })

    # Market evidence
    if market_result and market_result.get("market_data"):
        info = market_result["market_data"].get(ticker)

        if info:
            evidence.append({
                "citation_id": f"{ticker}-market-1",
                "source": "market",
                "text": str(info),
                "supports": "market metrics"
            })

    return evidence

    

            





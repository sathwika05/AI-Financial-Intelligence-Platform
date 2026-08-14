import logging

from langsmith import traceable


logger = logging.getLogger(__name__)






def extract_sql_rows(db_result) -> list:
    """
    Normalize common database-result structures into a list of rows.
    """
    if db_result is None:
        return []

    if isinstance(db_result, list):
        return db_result

    if isinstance(db_result, tuple):
        return list(db_result)

    if isinstance(db_result, dict):
        for key in ("rows", "data", "results", "result"):
            value = db_result.get(key)

            if isinstance(value, list):
                return value

        # Treat a single dictionary as one database row
        return [db_result]

    return [db_result]


def record_matches_company(
    record: dict,
    company: dict,
) -> bool:
    """
    Decide whether one evidence record belongs to one company.

    Shared by the reranker's coverage backfill and the evidence
    attachment below so both stages agree on ownership. Every clause
    guards against None on both sides: market candidates carry no
    company_id and SQL rows may carry no ticker, so an unguarded
    None == None matches everything.
    """
    ticker = (company.get("ticker") or "").upper()
    name = (company.get("name") or "").lower()
    company_id = company.get(
        "company_id",
        company.get("id"),
    )

    metadata = record.get("metadata") or {}
    text = (
        record.get("content")
        or record.get("text")
        or ""
    )

    record_company_id = metadata.get("company_id")
    record_ticker = (
        metadata.get("ticker") or ""
    ).upper()

    return bool(
        (
            company_id is not None
            and record_company_id == company_id
        )
        or (ticker and record_ticker == ticker)
        or (ticker and ticker in text.upper())
        or (name and name in text.lower())
    )


def _build_metrics_evidence(
    company: dict,
    ticker: str,
) -> list[dict]:
    """
    Turn the ranker's DB metrics into a citable evidence item.

    The analysis prompt shows PE / EPS / revenue growth / market cap and
    is told to use them, but those values live on company["metrics"] and
    used to belong to no evidence item. With nothing valid to cite the
    model attached them to whichever SQL row it had, and the reviewer
    correctly flagged the claim as ungrounded.
    """
    metrics = company.get("metrics") or {}

    labelled = (
        ("pe_ratio", "P/E ratio"),
        ("eps", "EPS"),
        ("revenue_growth", "revenue growth"),
        ("market_cap", "market cap"),
    )

    parts = [
        f"{label}={metrics.get(key)}"
        for key, label in labelled
        if metrics.get(key) is not None
    ]

    if not parts:
        return []

    name = company.get("name") or ticker

    return [
        {
            "citation_id": f"{ticker}-metrics-1",
            "source": "metrics",
            "text": (
                f"{name} ({ticker}): "
                + ", ".join(parts)
                + "."
            ),
            "supports": "valuation/growth metrics",
        }
    ]


@traceable(
    name="attach_company_evidence",
    run_type="chain",
    tags=["scoring", "evidence"],
)
def attach_company_evidence(company: dict,
    intent: str,
    sql_result: dict | None = None,
    vector_result: dict | None = None,
    market_result: dict | None = None,
    reranked_context_records: list[dict] | None = None,) -> list[dict]:

    ticker = company.get("ticker", "").upper()
    name = company.get("name", "").lower()
    company_id = company.get("company_id", company.get("id"))

    evidence = []

    # Always citable: these values are shown to the analysis LLM and it
    # is instructed to use them, so they need a citation_id of their own.
    metrics_evidence = _build_metrics_evidence(
        company,
        ticker,
    )

    # ==========================================================
    # MIXED
    # Prefer reranked evidence selected by the LLM. If none of it
    # matched this company, fall through to the raw sources below
    # rather than returning empty — an unsupported company trips the
    # reviewer's missing-evidence check and burns a retrieval retry.
    # ==========================================================
    if (
        intent == "MIXED"
        and reranked_context_records
    ):
        for record in reranked_context_records:
            if not record_matches_company(
                record,
                company,
            ):
                continue

            text = record.get("content", "")

            evidence.append(
                {
                    "citation_id": (
                        f"{ticker}-"
                        f"{record['source_type']}-"
                        f"{record['candidate_id']}"
                    ),
                    "source": record["source_type"],
                    "text": text[:500],
                    "supports": record.get(
                        "supports",
                        "relevance",
                    ),
                    "rerank_score": record.get(
                        "rerank_score"
                    ),
                    "reason": record.get(
                        "rerank_reason",
                        "",
                    ),
                }
            )

        if evidence:
            return metrics_evidence + evidence

        logger.info(
            "[EVIDENCE] No reranked evidence matched %s; "
            "falling back to raw retrieval sources",
            ticker or name or company_id,
        )

    # SQL evidence
    # Retrieval publishes rows under "db_result"; "rows" is kept as a
    # fallback for callers that pass a pre-normalized payload.
    if sql_result:
        sql_rows = extract_sql_rows(
            sql_result.get("db_result")
            or sql_result.get("rows")
        )

        for i, row in enumerate(sql_rows):
            text = str(row)

            row_dict = row if isinstance(row, dict) else {}

            belongs = (
                (
                    company_id is not None
                    and row_dict.get("company_id") == company_id
                )
                or (ticker and ticker in text.upper())
                or (name and name in text.lower())
            )

            if belongs:
                evidence.append({
                    "citation_id": f"{ticker}-sql-{i+1}",
                    "source": "sql",
                    "text": text[:500],
                    "supports": "valuation/growth metrics"
                })

    # Vector/news/document evidence
    if vector_result and vector_result.get("retrieved_chunks"):
        for i, chunk in enumerate(vector_result["retrieved_chunks"]):
            text = chunk.get("content", "")

            belongs = (
                (
                    company_id is not None
                    and chunk.get("company_id") == company_id
                )
                or (ticker and ticker in text.upper())
                or (name and name in text.lower())
            )

            if belongs:
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

    return metrics_evidence + evidence

    

            





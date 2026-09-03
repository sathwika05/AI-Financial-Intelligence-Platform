"""
Turning an answer into candidate assertions, and a run into evidence.

The split is done by an LLM because prose does not decompose
deterministically. Everything the split produces is then filtered by
policy.py, which is where the definition of a claim actually lives.

The evidence is assembled here, from the question's own PipelineExecution.
Three sources, each labelled:

    document   what the reranker handed to analysis
    sql        the rows the query returned
    market     live price and trend rows

SQL rows are the easy omission and the expensive one. A valuation answer's
figures come from the database, not from any document, so an audit fed
only document chunks would mark every correct P/E UNSUPPORTED and report a
catastrophic rate for the route that works best.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)


# Characters of any single evidence item handed to the judge. Chunks run
# long, and a question can retrieve a dozen; without a cap one verbose
# filing crowds out every other source in the context window.
MAX_ITEM_CHARS = 1200


_SPLIT_INSTRUCTIONS = """\
Split the analyst's answer below into atomic factual assertions.

Rules:
- One single, self-contained assertion per item.
- Use the answer's own wording verbatim. Do NOT paraphrase, summarise, or
  add anything the answer does not say.
- Split compound sentences into separate assertions.
- Resolve pronouns to the company they refer to, so each item stands alone.
- Include figures, named-entity facts, comparisons, and statements of
  direction such as "margins improved" or "demand weakened".
- Include hedged statements too; they are filtered afterwards, not here.

Reply with JSON only: {"claims": ["...", "..."]}
"""


def split_prompt(answer: str) -> str:
    """Render the call that splits one answer into candidates."""
    return f"{_SPLIT_INSTRUCTIONS}\nANSWER:\n{answer}\n"


def parse_candidates(raw: str) -> list[str]:
    """
    Read the split back, returning nothing rather than raising.

    A split failure means no claims were measured, and the caller records
    zero. Zero claims is never treated as a perfect support rate — see
    ClaimAudit, where total_claims of 0 leaves every count at 0 rather
    than reporting 100%.
    """
    match = re.search(r"\{.*\}", (raw or "").strip(), re.DOTALL)

    if not match:
        logger.warning("[CLAIMS] Splitter returned no JSON object")
        return []

    try:
        payload = json.loads(match.group(0))
    except json.JSONDecodeError:
        logger.warning("[CLAIMS] Splitter returned invalid JSON")
        return []

    return [
        str(item).strip()
        for item in payload.get("claims", [])
        if str(item).strip()
    ]


def _truncate(text: str) -> str:
    return text if len(text) <= MAX_ITEM_CHARS else f"{text[:MAX_ITEM_CHARS]}…"


def evidence_from(execution: Any) -> list[str]:
    """
    Everything this question actually retrieved, labelled by source.

    Reranked contexts win over raw retrieved ones: the reranked set is
    what the analysis node was shown, and auditing against the pre-rerank
    list would grade the answer on evidence it never saw. Baseline runs
    have no reranker, so the raw list is the fallback rather than an
    error.
    """
    evidence: list[str] = []

    documents = (
        getattr(execution, "reranked_contexts", None)
        or getattr(execution, "retrieved_contexts", None)
        or []
    )

    for text in documents:
        if text:
            evidence.append(f"[document] {_truncate(str(text))}")

    for row in getattr(execution, "sql_rows", None) or []:
        evidence.append(f"[sql] {_truncate(json.dumps(row, default=str))}")

    market = getattr(execution, "market_result", None)

    if market:
        evidence.append(f"[market] {_truncate(json.dumps(market, default=str))}")

    return evidence

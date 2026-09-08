

import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from langchain_core.messages import HumanMessage
from langsmith import traceable
from pydantic import BaseModel, Field
from requests import session
from sqlalchemy.ext.asyncio import AsyncSession
from langchain_core.load import dumps

from backend.config import settings
from backend.escalation.service import record_escalation
from backend.graph.financial_graph import financial_graph
from backend.graph.run import run_graph
from backend.security import events
from backend.security.input_guard import InputGuard
from backend.security.output_validator import OutputValidator
from backend.security.pii import PIIDetector
from backend.security.concurrency import ConcurrencyBound
from backend.security.rate_limit import RateLimiter
from backend.llm.llm_config_service import LLMConfigService
from backend.observability.logging import query_run
from backend.services.postgres_service import get_db
from backend.state.state_factory import build_initial_financial_state
from backend.llm.usage_tracker import build_usage_config




class FinancialQueryRequest(BaseModel):
    query: str = Field(min_length=3, max_length=500)

logger = logging.getLogger(__name__)
router = APIRouter()

# One instance each: the patterns compile once rather than per request.
# Everything here costs about 0.4ms in total, measured, against a pipeline
# that takes roughly 10 to 45 seconds.
_input_guard = InputGuard()
_pii = PIIDetector()
_output_validator = OutputValidator()
_rate_limiter = RateLimiter(
    limit=settings.SECURITY_RATE_LIMIT,
    window_seconds=settings.SECURITY_RATE_WINDOW_SECONDS,
)

# A different ceiling from the one above, and not a substitute for it.
# The rate limiter bounds one caller over time; this bounds everyone at an
# instant. Five testers clicking together are five addresses, each inside
# its own limit, and all five pipelines start at once -- on 0.5 CPU and
# 512MB, against a provider ceiling of 8000 tokens per minute shared
# between them. Both have been hit: an OOM restart that 502'd whoever was
# mid-query, and a 429 that used to be reported as a hallucination.
_concurrency = ConcurrencyBound(
    limit=settings.SECURITY_MAX_CONCURRENT_QUERIES,
    retry_after_seconds=settings.SECURITY_CONCURRENCY_RETRY_AFTER_SECONDS,
)

# Traced separately from the route handler: @traceable adds a `config`
# kwarg to the wrapped signature, which FastAPI would expose as a query
# parameter in the OpenAPI schema.
@traceable(
    name="api_financial_query",
    run_type="chain",
    tags=["api", "entrypoint"],
)
async def _run_financial_query(query: str, llm_runtime):
    """Invoke the financial graph as the root span of the trace."""
    initial_state = build_initial_financial_state(query)

    # The tracker rides on the config, so every nested LLM call is counted
    # without any node having to know about it.
    config, usage = build_usage_config(llm_runtime)

    final_state = await run_graph(financial_graph, initial_state, config)

    # Merged in rather than mutated into state: the graph has already
    # finished, and these are facts about the run, not part of it.
    return {**final_state, **usage.totals()}


@router.post(
    "/api/retrieve/financial",
)
async def financial_retrieval(
    request: FinancialQueryRequest,
    http_request: Request,
    session: AsyncSession = Depends(get_db),
):
    """
    Unified hybrid retrieval endpoint.

    Graph flow:

    1. Intent      -> VALUATION / GROWTH / SENTIMENT / MIXED, or
                      OUT_OF_SCOPE, which exits here rather than
                      researching a greeting.
    2. Planner     -> decompose into SQL, vector and market subqueries.
    3. Retrieval   -> those three in parallel. Vector is pgvector cosine
                      similarity, then BM25 reranking of what it returned.
                      Corpus-wide lexical ranking fused by RRF, and the
                      cross-encoder, are both off unless retrieval_flags
                      turns them on -- which only the evaluation router
                      does, so the demo serves the first two stages.
    4. Scoring     -> weighted multi-dimensional ranking.
    5. Analysis    -> LLM structured report.
    6. Reviewer    -> grounding and hallucination checks, with one retry
                      path back to analysis.

    Request flow around it:

    1. Load the enabled default LLM provider.
    2. Load its configured models once.
    3. Build the request-scoped LLM runtime.
    4. Pass the runtime to LangGraph through config.
    5. Nodes reuse the same runtime without DB calls.
    """

    # Opened around the whole handler, error paths included, so every line
    # this request produces — here and in every node below it — is tagged
    # apart from a benchmark running concurrently in the background.
    # Set only once a permit is actually held, so the release below can
    # tell "this request was admitted" from "this request was refused
    # before it started". Releasing on the second would hand away a
    # permit belonging to whoever is still running.
    admitted = False

    with query_run():
        try:
            # ── Security, in order of cost ──────────────────────────────
            #
            # A query costs 10-45s and real provider spend, and preprod has
            # no authentication, so the ceiling is about cost rather than
            # login abuse. Fails open: see RateLimiter.
            caller = (
                http_request.client.host
                if http_request.client
                else "unknown"
            )
            decision = _rate_limiter.allow(caller)

            if not decision.allowed:
                await events.record(
                    kind="rate_limited",
                    detail=f"caller {caller}",
                    query=request.query,
                )

                raise HTTPException(
                    status_code=429,
                    detail=(
                        "Too many queries. Each one runs the full pipeline; "
                        f"try again in {decision.retry_after} seconds."
                    ),
                    headers={"Retry-After": str(decision.retry_after)},
                )

            # Admission, before any work and before the guards below --
            # a request that will not be served should not cost a PII
            # scan, let alone six graph stages.
            try:
                _concurrency.acquire_or_raise()
                admitted = True
            except ConcurrencyBound.Busy as busy:
                await events.record(
                    kind="rate_limited",
                    detail=(
                        f"concurrency limit {busy.limit} reached; "
                        f"caller {caller}"
                    ),
                    query=request.query,
                )

                raise HTTPException(
                    status_code=429,
                    detail=(
                        "The demo is answering as many questions as it can "
                        "at once. Each one runs a six-stage pipeline; try "
                        f"again in {busy.retry_after} seconds."
                    ),
                    headers={"Retry-After": str(busy.retry_after)},
                )

            # Instructions aimed at the assistant rather than questions
            # about the data. Tuned so ordinary finance wording — "act as
            # both issuer and network", "ignore the previous quarter" —
            # passes; see InputGuard.
            verdict = _input_guard.inspect(request.query)

            if verdict.blocked:
                await events.record(
                    kind="input_blocked",
                    detail=verdict.pattern or "injection pattern",
                    query=request.query,
                )

                raise HTTPException(status_code=400, detail=verdict.reason)

            # Masked before the query reaches the provider or LangSmith.
            # Traces are the copy that persists.
            found_pii = _pii.detect(request.query)
            safe_query = _input_guard.sanitize(
                _pii.mask(request.query) if found_pii else request.query
            )

            if found_pii:
                await events.record(
                    kind="input_pii",
                    detail=f"masked {sorted(found_pii)}",
                    query=request.query,
                )

            # The LLM guard would run here. It is off by default because it
            # is an API round trip — 1-3s against ~0.4ms for everything
            # above. Enable with SECURITY_LLM_GUARD_ENABLED=true; see
            # backend/security/llm_guard.py.

            logger.info("[FINANCIAL_ROUTES] Query: %s", safe_query,)

            llm_config_service = LLMConfigService(session)

            # UI does not send a provider for regular requests.
            # The backend loads the enabled default provider.
            llm_runtime = (
                await llm_config_service.load_default_runtime()
            )

            logger.info("[FINANCIAL_ROUTES] LLM runtime loaded: provider=%s, models=%s",
                        llm_runtime.provider_name,
                        llm_runtime.models,
                        )

            result = await _run_financial_query(
                safe_query,
                llm_runtime,
            )
            # print(json.dumps(json.loads(dumps(result)), indent=2))
            #
            # Logged rather than printed. This handler runs inside
            # query_run(), so as a log record the dump carries that tag and
            # stays separable from a benchmark running concurrently —
            # printing put the whole pipeline state on stdout untagged, in
            # the middle of everyone else's lines.
            #
            # Guarded because dumps() serialises the entire graph state, and
            # at INFO that cost would be paid on every user query and then
            # thrown away.
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "[FINANCIAL_ROUTES] pipeline state %s",
                    dumps(result),
                )

            # The report is checked on the way out as well as the query on
            # the way in. Personal data is masked and the report still goes,
            # because the analysis around it remains useful; a leaked
            # credential blocks it, because no version of that report is
            # worth returning.
            final_report = result.get("final_report")
            validation = _output_validator.validate(
                json.dumps(final_report, default=str)
                if final_report is not None
                else ""
            )

            if validation.findings:
                await events.record(
                    kind="output_blocked" if validation.blocked else "output_pii",
                    detail="; ".join(validation.findings),
                    query=safe_query,
                )

            if validation.blocked:
                raise HTTPException(
                    status_code=500,
                    detail=(
                        "The generated report was withheld because it "
                        "contained credential-like content."
                    ),
                )

            if validation.findings:
                final_report = json.loads(validation.output)

            # A report the reviewer withheld goes to the admin queue with
            # the draft attached, because the response no longer carries
            # it -- top_companies is empty by the time it gets here.
            #
            # Wrapped, because filing is a side effect of answering rather
            # than part of it: a queue that will not take the row must not
            # turn a completed pipeline run into a 500 for the analyst.
            try:
                filed = await record_escalation(
                    session,
                    query=safe_query,
                    final_report=final_report,
                    draft_report=result.get("draft_report"),
                )

                if filed is not None:
                    await session.commit()
            except Exception:
                logger.exception(
                    "[FINANCIAL_ROUTES] Could not file the escalation"
                )
                await session.rollback()

            return {
                "query":  safe_query,
                "provider": llm_runtime.provider_name,
                "final_report": final_report,
                "ranked_companies": result.get("ranked_companies", []),
                "scoring_result": result.get("scoring_result"),
            }

        except HTTPException:
            # A deliberate refusal — rate limit, blocked input, withheld
            # report. Without this the broad handler below turns every one
            # of them into an opaque 500, so a caller cannot tell "you are
            # sending too many" from "the pipeline fell over".
            raise

        except RuntimeError as exc:
            logger.exception(
                "[FINANCIAL_ROUTES] LLM configuration failed"
            )

            raise HTTPException(
                status_code=503,
                detail=str(exc),
            ) from exc

        except Exception as exc:
            logger.exception(
                "[FINANCIAL_ROUTES] Retrieval failed"
            )

            raise HTTPException(
                status_code=500,
                detail="Retrieval failed. Please try again.",
            ) from exc

        finally:
            # Every exit: the 500 above, a withheld report, a client that
            # hung up mid-pipeline. A permit held by a request that raised
            # is gone for the life of the process, and `limit` of those
            # means the demo answers nothing until it restarts.
            if admitted:
                _concurrency.release()
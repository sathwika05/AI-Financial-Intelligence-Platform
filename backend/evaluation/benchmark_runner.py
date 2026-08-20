from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from langchain_core.runnables import RunnableConfig
from langsmith import traceable
from langchain_core.load import dumps

from backend.evaluation.aggregation import (
    aggregate_benchmark_run,
    finalize_question_result,
)
from backend.llm.usage_tracker import UsageTracker
from backend.scoring.evidence_builder import extract_sql_rows
from backend.evaluation.datasets.question_sets import (
    get_question_set,
)
from backend.evaluation.evaluators.intent_evaluator import (
    IntentEvaluator,
)
from backend.evaluation.evaluators.market_evaluator import (
    MarketEvaluator,
)
from backend.evaluation.evaluators.ragas_evaluator import (
    RagasEvaluator,
)
from backend.evaluation.evaluators.ranking_evaluator import (
    RankingEvaluator,
)
from backend.evaluation.evaluators.sql_evaluator import (
    SQLEvaluator,
)
from backend.evaluation.evaluators.tool_evaluator import (
    ToolEvaluator,
)
from backend.evaluation.judges import (
    BenchmarkJudges,
    get_default_judges,
)
from backend.evaluation.schemas import (
    BenchmarkConfig,
    BenchmarkRunResult,
    BenchmarkStatus,
    EvalQuestion,
    EvaluatorResult,
    PipelineExecution,
    QuestionEvaluationResult,
)
from backend.observability.logging import log_span
from backend.retrieval.sql_executor import SCHEMA
from backend.state.state_factory import (
    build_initial_financial_state,
)


logger = logging.getLogger(__name__)


class BenchmarkRunner:
    """
    Execute a selected question set through the financial graph
    and run the six evaluation components.
    """

    def __init__(
        self,
        *,
        graph: Any,
        judges: BenchmarkJudges | None = None,
    ) -> None:
        """
        judges:
            The fixed LLM judges used by the SQL and RAGAS evaluators.
            Defaults to the shared judges so that every provider under
            test is graded identically. Injectable for offline tests.
        """
        self.graph = graph
        self.judges = (
            judges
            or get_default_judges()
        )

        self.intent_evaluator = IntentEvaluator()
        self.sql_evaluator = SQLEvaluator(
            judge_llm=self.judges.sql_llm
        )
        self.ragas_evaluator = RagasEvaluator(
            judge_llm=self.judges.ragas_llm,
            judge_embeddings=(
                self.judges.ragas_embeddings
            ),
        )
        self.tool_evaluator = ToolEvaluator()
        self.ranking_evaluator = RankingEvaluator()
        self.market_evaluator = MarketEvaluator()

    @log_span("run_id")
    async def run(
        self,
        *,
        config: BenchmarkConfig,
        runnable_config: RunnableConfig,
        run_id: UUID,
    ) -> BenchmarkRunResult:
        """
        Execute every question in config.question_set.

        runnable_config contains the provider-specific LLMRuntime,
        LangSmith tags, and LangSmith metadata.
        """
        result = BenchmarkRunResult(
            run_id=run_id,
            config=config,
            status=BenchmarkStatus.RUNNING,
        )

        try:
            questions = get_question_set(
                config.question_set
            )

            result.total_questions = len(
                questions
            )

            logger.info(
                "[BENCHMARK] Starting run_id=%s "
                "question_set=%s total_questions=%s",
                run_id,
                config.question_set,
                result.total_questions,
            )

            for question in questions:
                question_result = await self._run_question(
                    question=question,
                    benchmark_config=config,
                    runnable_config=runnable_config,
                )

                result.question_results.append(
                    question_result
                )

                if question_result.passed:
                    result.passed_questions += 1
                else:
                    result.failed_questions += 1

            result.aggregate_metrics = (
                aggregate_benchmark_run(
                    result
                )
            )

            result.status = BenchmarkStatus.COMPLETED

        except Exception as exc:
            logger.exception(
                "[BENCHMARK] Run failed run_id=%s",
                run_id,
            )

            result.status = BenchmarkStatus.FAILED
            result.error = str(exc)

        finally:
            result.completed_at = datetime.now(
                timezone.utc
            )

        return result

    @traceable(
        name="benchmark_question",
        run_type="chain",
        tags=["eval"],
    )
    @log_span("question.question_id", "question.expected_intent")
    async def _run_question(
        self,
        *,
        question: EvalQuestion,
        benchmark_config: BenchmarkConfig,
        runnable_config: RunnableConfig,
    ) -> QuestionEvaluationResult:
        """
        Execute one question and select evaluators by expected route.

        The benchmark configuration is not named `config` because
        @traceable treats a `config` argument as a LangChain
        RunnableConfig and calls .get() on it.

        VALUATION/GROWTH:
            intent + SQL + optional tool + optional ranking

        SENTIMENT:
            intent + RAGAS + optional tool + optional ranking

        MIXED:
            intent + SQL + RAGAS + tool + ranking + market
        """
        try:
            execution = await self._execute_pipeline(
                question=question,
                runnable_config=runnable_config,
            )

            # print(json.dumps(json.loads(dumps(execution)), indent=2))
            #
            # Routed through the logger instead. print() writes straight to
            # stdout with no run tag, so a concurrent request's log lines
            # land in the middle of the JSON and the block stops parsing —
            # which is how a whole run's per-question detail became
            # unreadable. As a log record it carries bench:<run_id>, can be
            # filtered out of a busy stream, and stays off unless DEBUG is
            # enabled.
            #
            # Serialised lazily: dumps() walks the entire pipeline state,
            # and at INFO that work would be done and then discarded.
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "[BENCHMARK] execution question_id=%s %s",
                    question.question_id,
                    dumps(execution),
                )

            evaluator_results: dict[
                str,
                EvaluatorResult,
            ] = {}

            # Intent applies to every question.
            evaluator_results["intent"] = (
                self.intent_evaluator.evaluate(
                    expected_intent=(
                        question.expected_intent.value
                    ),
                    actual_intent=(
                        execution.actual_intent
                    ),
                )
            )

            route = question.expected_intent.value

            # Only run ToolEvaluator when golden expected tools exist.
            if question.expected_tools:
                evaluator_results["tool"] = (
                    await self.tool_evaluator.evaluate(
                        user_query=question.question,
                        actual_tool_calls=self._to_tool_calls(
                            execution.executed_tools
                        ),
                        expected_tool_calls=self._to_tool_calls(
                            question.expected_tools
                        ),
                    )
                )

            # SQL applies to valuation, growth, and mixed questions.
            if route in {
                "VALUATION",
                "GROWTH",
                "MIXED",
            }:
                evaluator_results["sql"] = (
                    await self.sql_evaluator.evaluate(
                        generated_sql=(
                            execution.generated_sql
                        ),
                        actual_result=(
                            execution.sql_rows
                        ),
                        expected_result=(
                            question.expected_sql_result
                        ),
                        expected_sql=(
                            question.expected_sql
                        ),
                        database_schema=SCHEMA,
                        sql_order_requirement=(
                            question.sql_order_requirement
                        ),
                    )
                )

            # RAGAS applies to sentiment and mixed questions.
            if route in {
                "SENTIMENT",
                "MIXED",
            }:
                if route == "SENTIMENT":
                    contexts = execution.retrieved_contexts

                else:
                    contexts = execution.reranked_contexts

                # The document subset, for the retrieval metrics only.
                #
                # SENTIMENT retrieves documents and nothing else, so its
                # contexts are already the subset. MIXED mixes document
                # chunks with live market rows, and the reranker's
                # source_type is the only thing that separates them.
                document_contexts = (
                    contexts
                    if route == "SENTIMENT"
                    else self._document_contexts(
                        execution.reranked_context_records
                    )
                )

                evaluator_results["ragas"] = (
                    await self.ragas_evaluator.evaluate(
                        question=question.question,
                        answer=self._answer_to_text(
                            execution.final_answer
                        ),
                        contexts=contexts,
                        reference_answer=(
                            question.reference_answer
                        ),
                        reference_contexts=(
                            question.reference_contexts
                        ),
                        document_contexts=document_contexts,
                    )
                )

            # Ranking applies only when the golden set contains companies.
            if question.expected_companies:
                evaluator_results["ranking"] = (
                    self.ranking_evaluator.evaluate(
                        ranked_companies=(
                            execution.ranked_companies
                        ),
                        expected_companies=(
                            question.expected_companies
                        ),
                        k=benchmark_config.top_k,
                    )
                )

            # Market evaluation is currently part of mixed questions.
            if route == "MIXED":
                evaluator_results["market"] = (
                    self.market_evaluator.evaluate(
                        market_result=(
                            execution.market_result
                        ),
                        expected_companies=(
                            question.expected_companies
                        ),
                    )
                )

            question_result = QuestionEvaluationResult(
                question_id=question.question_id,
                question=question.question,
                expected_intent=route,
                actual_intent=execution.actual_intent,
                execution=execution,
                evaluator_results=evaluator_results,
            )

            question_result = finalize_question_result(
                question_result
            )

            # print(question_result.model_dump_json(indent=2))
            #
            # Logged rather than printed, for the same reason as above.
            #
            # Emitted after finalization, because overall_score, passed and
            # aggregate_metrics are computed there — dumping earlier always
            # showed the schema defaults (0.0 / False / {}) however the
            # question actually scored.
            #
            # This is currently the only per-question record that exists:
            # evaluation_metrics stores run-level aggregates and has no
            # question_id, so nothing else keeps a question's individual
            # scores, its ordering diagnostics, or the equivalence judge's
            # reasoning. Kept at INFO for that reason, where the execution
            # dump above is DEBUG — one is a summary, the other is the whole
            # pipeline state.
            logger.info(
                "[BENCHMARK] result question_id=%s overall=%s passed=%s %s",
                question_result.question_id,
                question_result.overall_score,
                question_result.passed,
                question_result.model_dump_json(),
            )

            return question_result

        except Exception as exc:
            logger.exception(
                "[BENCHMARK] Question failed "
                "question_id=%s",
                question.question_id,
            )

            return QuestionEvaluationResult(
                question_id=question.question_id,
                question=question.question,
                expected_intent=(
                    question.expected_intent.value
                ),
                execution=PipelineExecution(),
                passed=False,
                error=str(exc),
            )

    @log_span()
    async def _execute_pipeline(
        self,
        *,
        question: EvalQuestion,
        runnable_config: RunnableConfig,
    ) -> PipelineExecution:
        """
        Build a clean initial FinancialState and invoke LangGraph.
        """
        started_at = time.perf_counter()

        initial_state = build_initial_financial_state(
            question.question
        )

        # A tracker per question, not per run: one shared instance would pool
        # every question's tokens into whichever result read it last. The
        # incoming config is preserved so tracing tags and any existing
        # callbacks survive.
        runtime = (
            runnable_config.get("configurable") or {}
        ).get("llm_runtime")

        usage = UsageTracker(runtime)

        question_config = {
            **runnable_config,
            "configurable": {
                **(runnable_config.get("configurable") or {}),
            },
            "callbacks": [
                *(runnable_config.get("callbacks") or []),
                usage,
            ],
        }

        final_state = await self.graph.ainvoke(
            initial_state,
            config=question_config,
        )

        latency_ms = (
            time.perf_counter() - started_at
        ) * 1000

        return self._extract_execution(
            final_state=final_state,
            latency_ms=latency_ms,
            usage=usage.totals(),
        )

    @staticmethod
    def _extract_execution(
        *,
        final_state: dict[str, Any],
        latency_ms: float,
        usage: dict[str, Any] | None = None,
    ) -> PipelineExecution:
        """
        Normalize FinancialState fields into PipelineExecution.
        """
        retrieved_contexts = final_state.get(
            "retrieved_contexts",
            [],
        )

        # Compatibility fallback while older vector nodes still place
        # chunks only inside vector_result.
        if not retrieved_contexts:
            vector_result = (
                final_state.get("vector_result")
                or {}
            )

            if isinstance(vector_result, dict):
                retrieved_contexts = (
                    vector_result.get(
                        "chunks",
                        [],
                    )
                )

        return PipelineExecution(
            actual_intent=final_state.get(
                "intent"
            ),
            # `sql_query` is the planner's natural-language sub-query, not
            # SQL. The executed statement is inside sql_result, which is why
            # sql_equivalence had nothing to compare and always returned None.
            generated_sql=(
                (final_state.get("sql_result") or {}).get("generated_sql")
                or final_state.get("generated_sql")
                or None
            ),
            sql_result=final_state.get(
                "sql_result"
            ),
            sql_rows=extract_sql_rows(
                (final_state.get("sql_result") or {}).get("db_result")
            ),
            retrieved_contexts=(
                BenchmarkRunner._contexts_to_text(
                    retrieved_contexts
                )
            ),
            reranked_contexts=(
                BenchmarkRunner._contexts_to_text(
                    final_state.get(
                        "reranked_contexts",
                        [],
                    )
                )
            ),
            # Carried alongside the flattened text so the RAGAS evaluator
            # can tell a document chunk from a market row.
            reranked_context_records=[
                record
                for record in final_state.get(
                    "reranked_context_records",
                    [],
                )
                if isinstance(record, dict)
            ],
            market_result=final_state.get(
                "market_result"
            ),
            ranked_companies=final_state.get(
                "ranked_companies",
                [],
            ),
            executed_tools=final_state.get(
                "executed_tools",
                [],
            ),
            node_timings=final_state.get(
                "node_timings",
                [],
            ),
            final_answer=(
                final_state.get("final_report")
                or final_state.get(
                    "draft_report"
                )
            ),
            latency_ms=round(
                latency_ms,
                3,
            ),
            # Measured by the usage tracker. The `total_cost_usd` state key
            # this used to read was never written by any node, which is why
            # every run reported a cost of zero.
            cost_usd=(usage or {}).get(
                "total_cost_usd"
            ),
            input_tokens=(usage or {}).get(
                "input_tokens",
                0,
            ),
            output_tokens=(usage or {}).get(
                "output_tokens",
                0,
            ),
            llm_calls=(usage or {}).get(
                "llm_calls",
                0,
            ),
            raw_state=final_state,
        )

    @staticmethod
    def _to_tool_calls(
        tool_names: list[str],
    ) -> list[dict[str, Any]]:
        """
        Convert high-level stage names into the structured tool calls
        ToolEvaluator expects.

        Tool evaluation is scored at the stage level, the same level the
        dashboard reports: sql, vector, market, planner. Arguments are left
        empty on both the expected and the actual side, so the RAGAS
        metrics compare stage names only.
        """
        return [
            {
                "name": str(name).strip().lower(),
                "args": {},
            }
            for name in tool_names
            if name
        ]

    @staticmethod
    def _document_contexts(
        records: list[dict[str, Any]],
    ) -> list[str]:
        """
        Text of the reranked contexts that came from the document corpus.

        The reranker labels every candidate with a source_type, and only
        "vector" records are retrieved documents — "market" is a live price
        row and "sql" is a database result. Both are legitimate evidence
        for the answer, and neither says anything about how well document
        retrieval performed.

        Returns an empty list when nothing matches, and the caller falls
        back to the full context set rather than scoring against nothing.
        """
        return BenchmarkRunner._contexts_to_text(
            [
                record
                for record in records
                if record.get("source_type") == "vector"
            ]
        )

    @staticmethod
    def _contexts_to_text(
        contexts: list[Any],
    ) -> list[str]:
        """Convert strings, dictionaries, or Documents to plain text."""
        output: list[str] = []

        for context in contexts:
            if isinstance(context, str):
                output.append(context)

            elif isinstance(context, dict):
                text = (
                    context.get("text")
                    or context.get("page_content")
                    or context.get("content")
                )

                if text:
                    output.append(
                        str(text)
                    )

            elif hasattr(
                context,
                "page_content",
            ):
                output.append(
                    str(context.page_content)
                )

        return output

    @staticmethod
    def _answer_to_text(
        answer: Any,
    ) -> str:
        """Convert the structured report into text for RAGAS."""
        if answer is None:
            return ""

        if isinstance(answer, str):
            return answer

        if isinstance(answer, dict):
            parts: list[str] = []

            query_summary = answer.get(
                "query_summary"
            )

            if query_summary:
                parts.append(
                    str(query_summary)
                )

            companies = (
                answer.get("companies")
                or answer.get("top_companies")
                or []
            )

            for company in companies:
                if not isinstance(
                    company,
                    dict,
                ):
                    continue

                summary = company.get(
                    "summary"
                )

                if summary:
                    parts.append(
                        str(summary)
                    )

            return "\n".join(parts)

        return str(answer)

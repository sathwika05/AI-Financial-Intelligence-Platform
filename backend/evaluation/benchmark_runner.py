from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from langchain_core.runnables import RunnableConfig
from langsmith import traceable

from backend.evaluation.aggregation import (
    aggregate_benchmark_run,
    finalize_question_result,
)
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
                            execution.sql_result
                        ),
                        expected_result=(
                            question.expected_sql_result
                        ),
                        expected_sql=(
                            question.expected_sql
                        ),
                        database_schema=SCHEMA,
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

            return finalize_question_result(
                question_result
            )

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

        final_state = await self.graph.ainvoke(
            initial_state,
            config=runnable_config,
        )

        latency_ms = (
            time.perf_counter() - started_at
        ) * 1000

        return self._extract_execution(
            final_state=final_state,
            latency_ms=latency_ms,
        )

    @staticmethod
    def _extract_execution(
        *,
        final_state: dict[str, Any],
        latency_ms: float,
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
            generated_sql=final_state.get(
                "sql_query"
            ),
            sql_result=final_state.get(
                "sql_result"
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
            cost_usd=final_state.get(
                "total_cost_usd"
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

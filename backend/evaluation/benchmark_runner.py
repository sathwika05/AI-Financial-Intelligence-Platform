from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any

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
from backend.evaluation.schemas import (
    BenchmarkConfig,
    BenchmarkRunResult,
    BenchmarkStatus,
    EvalQuestion,
    PipelineExecution,
    QuestionEvaluationResult,
)


class BenchmarkRunner:
    def __init__(
        self,
        *,
        graph: Any,
    ) -> None:
        self.graph = graph

        self.intent_evaluator = IntentEvaluator()
        self.sql_evaluator = SQLEvaluator()
        self.tool_evaluator = ToolEvaluator()
        self.ranking_evaluator = RankingEvaluator()
        self.market_evaluator = MarketEvaluator()
        self.ragas_evaluator = RagasEvaluator()

    async def run(
        self,
        config: BenchmarkConfig,
    ) -> BenchmarkRunResult:
        result = BenchmarkRunResult(
            config=config,
            status=BenchmarkStatus.RUNNING,
        )

        try:
            questions = get_question_set(
                config.question_set
            )

            result.total_questions = len(questions)

            for question in questions:
                question_result = await self._run_question(
                    question=question,
                    config=config,
                )

                result.question_results.append(
                    question_result
                )

                if question_result.passed:
                    result.passed_questions += 1
                else:
                    result.failed_questions += 1

            result.aggregate_metrics = aggregate_benchmark_run(
                result
            )

            result.status = BenchmarkStatus.COMPLETED

        except Exception as exc:
            result.status = BenchmarkStatus.FAILED
            result.error = str(exc)

        finally:
            result.completed_at = datetime.now(timezone.utc)

        return result

    async def _run_question(
        self,
        *,
        question: EvalQuestion,
        config: BenchmarkConfig,
    ) -> QuestionEvaluationResult:
        try:
            execution = await self._execute_pipeline(
                question=question
            )

            evaluator_results = {}

            evaluator_results["intent"] = (
                self.intent_evaluator.evaluate(
                    expected_intent=question.expected_intent.value,
                    actual_intent=execution.actual_intent,
                )
            )

            evaluator_results["tool"] = (
                self.tool_evaluator.evaluate(
                    expected_tools=question.expected_tools,
                    executed_tools=execution.executed_tools,
                )
            )

            route = question.expected_intent.value.upper()

            if route in {
                "VALUATION",
                "GROWTH",
                "MIXED",
            }:
                evaluator_results["sql"] = (
                    self.sql_evaluator.evaluate(
                        generated_sql=execution.generated_sql,
                        actual_result=execution.sql_result,
                        expected_result=(
                            question.expected_sql_result
                        ),
                        expected_sql=question.expected_sql,
                    )
                )

            if route in {
                "SENTIMENT",
                "MIXED",
            }:
                answer = self._answer_to_text(
                    execution.final_answer
                )

                contexts = (
                    execution.reranked_contexts
                    or execution.retrieved_contexts
                )

                evaluator_results["ragas"] = (
                    await self.ragas_evaluator.evaluate(
                        question=question.question,
                        answer=answer,
                        contexts=contexts,
                        reference_answer=(
                            question.reference_answer
                        ),
                        reference_contexts=(
                            question.reference_contexts
                        ),
                    )
                )

            if question.expected_companies:
                evaluator_results["ranking"] = (
                    self.ranking_evaluator.evaluate(
                        ranked_companies=(
                            execution.ranked_companies
                        ),
                        expected_companies=(
                            question.expected_companies
                        ),
                        k=config.top_k,
                    )
                )

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
                expected_intent=(
                    question.expected_intent.value
                ),
                actual_intent=execution.actual_intent,
                execution=execution,
                evaluator_results=evaluator_results,
            )

            return finalize_question_result(
                question_result
            )

        except Exception as exc:
            empty_execution = PipelineExecution()

            return QuestionEvaluationResult(
                question_id=question.question_id,
                question=question.question,
                expected_intent=(
                    question.expected_intent.value
                ),
                execution=empty_execution,
                passed=False,
                error=str(exc),
            )

    async def _execute_pipeline(
        self,
        *,
        question: EvalQuestion,
    ) -> PipelineExecution:
        started_at = time.perf_counter()

        initial_state = {
            "messages": [],
            "original_query": question.question,
            "retry_count": 0,
            "should_retry": False,
            "executed_tools": [],
        }

        final_state = await self.graph.ainvoke(
            initial_state
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
        vector_result = (
            final_state.get("vector_result")
            or {}
        )

        retrieved_contexts = final_state.get(
            "retrieved_contexts",
            [],
        )

        if not retrieved_contexts:
            retrieved_contexts = (
                vector_result.get("chunks", [])
                if isinstance(vector_result, dict)
                else []
            )

        return PipelineExecution(
            actual_intent=final_state.get("intent"),

            generated_sql=final_state.get("sql_query"),
            sql_result=final_state.get("sql_result"),

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
                or final_state.get("draft_report")
            ),

            latency_ms=round(latency_ms, 3),

            cost_usd=final_state.get(
                "total_cost_usd"
            ),

            raw_state=final_state,
        )

    @staticmethod
    def _contexts_to_text(
        contexts: list[Any],
    ) -> list[str]:
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
                    output.append(str(text))

            elif hasattr(context, "page_content"):
                output.append(
                    str(context.page_content)
                )

        return output

    @staticmethod
    def _answer_to_text(answer: Any) -> str:
        if answer is None:
            return ""

        if isinstance(answer, str):
            return answer

        if isinstance(answer, dict):
            companies = answer.get("companies", [])
            parts = [
                str(answer.get("query_summary", ""))
            ]

            for company in companies:
                if isinstance(company, dict):
                    parts.append(
                        str(company.get("summary", ""))
                    )

            return "\n".join(
                part
                for part in parts
                if part
            )

        return str(answer)
"""
RAGAS (Retrieval-Augmented Generation Assessment) evaluator.

Purpose
-------
Measure answer grounding, answer relevance, and retrieval quality.

Golden dataset inputs
---------------------
reference_answer
reference_contexts

Pipeline outputs
----------------
question
answer
contexts

Metrics produced
----------------
faithfulness
response_relevancy
context_precision
context_recall
context_entity_recall
noise_sensitivity


RAG = Retrieval-Augmented Generation
RAGAS = Retrieval-Augmented Generation Assessment

"""
from __future__ import annotations

import logging
import math
from typing import Any

from backend.evaluation.schemas import EvaluatorResult
from backend.observability.logging import log_span


logger = logging.getLogger(__name__)


class RagasEvaluator:
    """Evaluate answer grounding and retrieval quality with RAGAS."""

    def __init__(
        self,
        *,
        judge_llm: Any,
        judge_embeddings: Any,
    ) -> None:
        """
        judge_llm:
            LangChain model wrapped with LangchainLLMWrapper.

        judge_embeddings:
            LangChain embeddings wrapped with LangchainEmbeddingsWrapper.

        Use one fixed LLM (Large Language Model) judge configuration across all benchmark providers.
        """
        self.judge_llm = judge_llm
        self.judge_embeddings = judge_embeddings

    @log_span("contexts")
    async def evaluate(
        self,
        *,
        question: str,
        answer: str,
        contexts: list[str],
        reference_answer: str | None,
        reference_contexts: list[str],
        document_contexts: list[str] | None = None,
    ) -> EvaluatorResult:
        if not answer.strip():
            return EvaluatorResult(
                evaluator="ragas",
                applicable=True,
                passed=False,
                score=0.0,
                metrics={},
                details={},
                errors=[
                    "The pipeline returned an empty answer."
                ],
            )

        if not contexts:
            return EvaluatorResult(
                evaluator="ragas",
                applicable=True,
                passed=False,
                score=0.0,
                metrics={
                    "faithfulness": 0.0,
                    "response_relevancy": 0.0,
                    "context_precision": 0.0,
                    "context_recall": 0.0,
                    "context_entity_recall": 0.0,
                    "noise_sensitivity": 1.0,
                },
                details={
                    "context_count": 0,
                },
                errors=[
                    "No retrieved contexts were available."
                ],
            )

        try:
            scores = await self._score(
                question=question,
                answer=answer,
                contexts=contexts,
                reference_answer=reference_answer,
                reference_contexts=reference_contexts,
                document_contexts=document_contexts,
            )

            # Higher is better for all metrics except noise_sensitivity.
            quality_values: list[float] = []

            for name, value in scores.items():
                if value is None:
                    continue

                quality_values.append(
                    1.0 - value
                    if name == "noise_sensitivity"
                    else value
                )

            overall_score = (
                sum(quality_values)
                / len(quality_values)
                if quality_values
                else 0.0
            )

            return EvaluatorResult(
                evaluator="ragas",
                applicable=True,
                passed=overall_score >= 0.70,
                score=round(
                    overall_score,
                    4,
                ),
                metrics={
                    name: round(value, 4)
                    for name, value in scores.items()
                    if value is not None
                },
                details={
                    "context_count": len(contexts),
                    "has_reference_answer": bool(
                        reference_answer
                    ),
                    "reference_context_count": len(
                        reference_contexts
                    ),
                },
                errors=[],
            )

        except Exception as exc:
            logger.exception(
                "[RAGAS_EVALUATOR] Evaluation failed"
            )

            return EvaluatorResult(
                evaluator="ragas",
                applicable=True,
                passed=False,
                score=0.0,
                metrics={},
                details={
                    "context_count": len(contexts),
                },
                errors=[
                    f"RAGAS evaluation failed: {exc}"
                ],
            )

    async def _score(
        self,
        *,
        question: str,
        answer: str,
        contexts: list[str],
        reference_answer: str | None,
        reference_contexts: list[str],
        document_contexts: list[str] | None = None,
    ) -> dict[str, float | None]:
        from ragas import SingleTurnSample
        from ragas.metrics import (
            ContextEntityRecall,
            Faithfulness,
            LLMContextPrecisionWithReference,
            LLMContextPrecisionWithoutReference,
            LLMContextRecall,
            NoiseSensitivity,
            ResponseRelevancy,
        )

        # Two samples, because the metrics below answer two different
        # questions and need different context sets.
        #
        # The generation metrics — faithfulness, response_relevancy,
        # noise_sensitivity — ask whether the answer is grounded in what the
        # pipeline was given. They see everything, market rows included:
        # removing a context the answer legitimately cites would make a
        # grounded claim look unsupported.
        #
        # The retrieval metrics — precision, recall, entity recall — ask how
        # good the document retrieval was, and are scored over documents
        # alone. Grading them across a MIXED question's fourteen contexts,
        # eleven of which are live price rows, measured the market API
        # instead: context_precision read 0.1186 while retrieval itself was
        # sound.
        generation_sample = SingleTurnSample(
            user_input=question,
            response=answer,
            retrieved_contexts=contexts,
            reference=reference_answer,
            reference_contexts=reference_contexts,
        )

        retrieval_sample = SingleTurnSample(
            user_input=question,
            response=answer,
            retrieved_contexts=document_contexts or contexts,
            reference=reference_answer,
            reference_contexts=reference_contexts,
        )

        # Kept as `sample` for the generation metrics that follow.
        sample = generation_sample

        # Metrics that do not require a golden answer.
        scores: dict[str, float | None] = {
            "faithfulness": await self._safe_score(
                Faithfulness(
                    llm=self.judge_llm
                ),
                sample,
            ),
            "response_relevancy": await self._safe_score(
                ResponseRelevancy(
                    llm=self.judge_llm,
                    embeddings=self.judge_embeddings,
                ),
                sample,
            ),
            "context_precision": None,
            "context_recall": None,
            "context_entity_recall": None,
            "noise_sensitivity": None,
        }

        # Context precision can run with or without a reference answer.
        if reference_answer:
            precision_metric = (
                LLMContextPrecisionWithReference(
                    llm=self.judge_llm
                )
            )
        else:
            precision_metric = (
                LLMContextPrecisionWithoutReference(
                    llm=self.judge_llm
                )
            )

        scores["context_precision"] = await self._safe_score(
            precision_metric,
            retrieval_sample,
        )

        # These metrics require golden reference information.
        if reference_answer:
            scores["context_recall"] = await self._safe_score(
                LLMContextRecall(
                    llm=self.judge_llm
                ),
                retrieval_sample,
            )

            scores["context_entity_recall"] = await self._safe_score(
                ContextEntityRecall(
                    llm=self.judge_llm
                ),
                retrieval_sample,
            )

            scores["noise_sensitivity"] = await self._safe_score(
                NoiseSensitivity(
                    llm=self.judge_llm
                ),
                sample,
            )

        return scores

    @staticmethod
    async def _safe_score(
        metric: Any,
        sample: Any,
    ) -> float | None:
        value = await metric.single_turn_ascore(
            sample
        )

        numeric = float(value)

        if math.isnan(numeric):
            return None

        return max(
            0.0,
            min(
                1.0,
                numeric,
            ),
        )

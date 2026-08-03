from __future__ import annotations

from typing import Any

from backend.evaluation.schemas import EvaluatorResult


class RagasEvaluator:
    name = "ragas"

    async def evaluate(
        self,
        *,
        question: str,
        answer: str,
        contexts: list[str],
        reference_answer: str | None = None,
        reference_contexts: list[str] | None = None,
    ) -> EvaluatorResult:
        if not answer:
            return EvaluatorResult(
                evaluator=self.name,
                applicable=True,
                passed=False,
                metrics={},
                errors=["Answer is empty."],
            )

        if not contexts:
            return EvaluatorResult(
                evaluator=self.name,
                applicable=True,
                passed=False,
                metrics={},
                errors=["No retrieval contexts were provided."],
            )

        try:
            metrics = await self._run_ragas(
                question=question,
                answer=answer,
                contexts=contexts,
                reference_answer=reference_answer,
                reference_contexts=reference_contexts or [],
            )

            faithfulness = metrics.get("faithfulness")
            passed = (
                faithfulness is not None
                and faithfulness >= 0.75
            )

            return EvaluatorResult(
                evaluator=self.name,
                applicable=True,
                passed=passed,
                metrics=metrics,
            )

        except Exception as exc:
            return EvaluatorResult(
                evaluator=self.name,
                applicable=True,
                passed=False,
                metrics={},
                errors=[str(exc)],
            )

    async def _run_ragas(
        self,
        *,
        question: str,
        answer: str,
        contexts: list[str],
        reference_answer: str | None,
        reference_contexts: list[str],
    ) -> dict[str, float]:
        """
        Connect this method to your current RAGAS implementation.

        Expected output example:

        {
            "faithfulness": 0.88,
            "response_relevancy": 0.84,
            "context_precision": 0.81,
            "context_recall": 0.79,
            "context_entity_recall": 0.76,
            "noise_sensitivity": 0.12,
        }
        """

        raise NotImplementedError(
            "Connect _run_ragas() to the existing RAGAS code."
        )
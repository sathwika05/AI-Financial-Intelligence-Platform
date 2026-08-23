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


# Failures that say nothing about the pipeline's quality.
#
# A quota, rate-limit or auth error means the judge could not be called at
# all. Scoring that 0.0 reports the strongest possible negative result about
# retrieval and grounding on the basis of a billing problem — run 68cce08a
# recorded mixed_001 at ragas 0.0 with an empty metrics dict because the
# OpenAI balance ran out on the last metric, and the question dropped from
# 0.9103 to 0.784 with nothing about the pipeline having changed.
#
# These still fail the question, because an unmeasured question is not a
# passing one, but they are tagged so a reader can tell "we could not
# measure this" from "this scored zero".
_INFRASTRUCTURE_MARKERS = (
    "insufficient_quota",
    "credit_balance_exhausted",
    # Three spellings, all seen in the wild: the API's error code
    # (rate_limit_exceeded), a prose message ("Rate limit reached for
    # gpt-4"), and the SDK's exception class name (RateLimitError), which
    # is all that is available when the message carries no detail.
    "rate_limit",
    "rate limit",
    "ratelimit",
    "429",
    "401",
    "invalid_api_key",
    "authentication",
    "connection error",
    "timeout",
)


def _is_infrastructure_error(exc: Exception) -> bool:
    """True when the judge could not be reached, rather than scoring badly."""
    text = f"{type(exc).__name__} {exc}".lower()

    return any(
        marker in text
        for marker in _INFRASTRUCTURE_MARKERS
    )


# Which RAGAS metrics decide pass or fail. Everything scored is still
# reported; this only governs the gate.
#
# context_entity_recall is deliberately absent. It looks for the entities a
# reference answer names inside the retrieved DOCUMENTS, which is the wrong
# evidence source for half of what a mixed or sentiment answer must say:
# valuation and growth claims come from financial_metrics, and no news
# article contains a P/E ratio. In run a88968e8 it averaged 0.321 and
# correlated -0.08 with the figures in the answer — editing the goldens did
# not move it — while correlating +0.42 with how much of the cited evidence
# retrieval returned. It also moved 0.643 -> 0.286 between runs on an
# unedited question. A number that noisy, measuring against a source that
# cannot hold the claim, should inform rather than decide.
#
# response_relevancy stays in. It was a candidate for removal when its
# noncommittal cliff was zeroing eight questions, but that was the pipeline
# hedging, and 9411cbd fixed it at the source.
# How much of each retrieved context to keep in the result.
#
# Enough to identify which chunk was retrieved, not enough to re-read the
# corpus out of question_results. context_recall compares the reference's
# claims against these; without them a 0.00 records that fifteen contexts
# existed and nothing about what they were, and every explanation for a low
# score is a guess. Three such guesses have already been tested and failed.
CONTEXT_PREVIEW_CHARS = 240


GATING_METRICS = frozenset({
    "faithfulness",
    "response_relevancy",
    "context_precision",
    "context_recall",
    "noise_sensitivity",
})


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
            # Every metric is reported; only GATING_METRICS decide pass.
            quality_values: list[float] = []

            for name, value in scores.items():
                if value is None or name not in GATING_METRICS:
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
                    "retrieved_contexts": [
                        context[:CONTEXT_PREVIEW_CHARS]
                        for context in contexts
                    ],
                    "reference_contexts_preview": [
                        context[:CONTEXT_PREVIEW_CHARS]
                        for context in reference_contexts
                    ],
                },
                errors=[],
            )

        except Exception as exc:
            infrastructure = _is_infrastructure_error(exc)

            if infrastructure:
                # Loud, because the number that follows is not a
                # measurement and no one should read it as one.
                logger.error(
                    "[RAGAS_EVALUATOR] Judge unreachable — this is NOT a "
                    "quality result: %s",
                    exc,
                )
            else:
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
                    "infrastructure_error": infrastructure,
                    "unmeasured": infrastructure,
                },
                errors=[
                    (
                        "RAGAS could not be measured — the judge was "
                        f"unreachable: {exc}"
                    )
                    if infrastructure
                    else f"RAGAS evaluation failed: {exc}"
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
        """One metric's score, or None if it could not produce one.

        None rather than an exception, because a metric that fails is a
        measurement lost, not a judgement made — and the composite already
        skips None, so it simply does not vote.

        Without this, one metric raising discarded all six. RAGAS threw a
        numpy error ("inhomogeneous shape") on six questions across four
        runs — sentiment_008 twice, mixed_005, mixed_014, mixed_015 — and
        each recorded 0.0 with no metrics, which the gate reads as a
        failure rather than as the absence of a result.
        """
        try:
            value = await metric.single_turn_ascore(
                sample
            )
        except Exception:
            logger.exception(
                "[RAGAS_EVALUATOR] %s failed; the other metrics still "
                "score",
                type(metric).__name__,
            )

            return None

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

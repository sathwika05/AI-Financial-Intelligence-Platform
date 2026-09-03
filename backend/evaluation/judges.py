"""
Fixed LLM (Large Language Model) judges used by the benchmark evaluators.

The judge configuration is deliberately independent of the provider being
benchmarked. A run against OpenAI and a run against Anthropic are graded by
the same judge, so their scores stay comparable.

Two judge objects are required because the evaluators use two different
RAGAS (Retrieval-Augmented Generation Assessment) interfaces:

ragas_llm / ragas_embeddings
    Metric classes in ragas.metrics, used by RagasEvaluator. They accept a
    BaseRagasLLM, so a LangChain model and embeddings are wrapped.

sql_llm
    Metric classes in ragas.metrics.collections, used by SQLEvaluator.
    SQLSemanticEquivalence accepts an InstructorBaseRagasLLM, which is built
    by ragas.llms.llm_factory over an OpenAI client.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from typing import Any
from backend.observability.logging import log_span


# Override to grade with a different judge; keep it stable across the runs
# you intend to compare, because judges do not agree in absolute terms — the
# same answer scored 0.45 under gpt-4o-mini and 0.61 under gpt-5.4-mini.
#
# The default is deliberately a model whose name ragas can parse. ragas 0.4.3
# picks OpenAI's token-limit parameter by reading the version out of the model
# name: it strips "gpt-", takes the leading segment and calls int() on it.
# int("5.4") raises, so it concludes the model is legacy and sends the retired
# `max_tokens`, which gpt-5.x rejects outright. Every SQLSemanticEquivalence
# call then errors, and since a question fails when any evaluator errors, no
# SQL-route question could ever pass. Any decimal-versioned name hits this.
JUDGE_MODEL = os.getenv(
    "BENCHMARK_JUDGE_MODEL",
    "gpt-4o-mini",
)

JUDGE_EMBEDDING_MODEL = os.getenv(
    "BENCHMARK_JUDGE_EMBEDDING_MODEL",
    "text-embedding-3-small",
)


@dataclass(frozen=True)
class BenchmarkJudges:
    """The judge models the evaluators need, resolved once per process."""

    ragas_llm: Any
    ragas_embeddings: Any
    sql_llm: Any

    # Plain chat model for the claim splitter and the claim judge.
    #
    # Neither goes through ragas, so neither wants a wrapper: they send a
    # prompt and read the text back. Same JUDGE_MODEL as the others, so a
    # run against OpenAI and one against Anthropic are audited by the same
    # judge and their claim rates stay comparable.
    claim_llm: Any


@lru_cache(maxsize=1)
@log_span()
def get_default_judges() -> BenchmarkJudges:
    """
    Build the default judges.

    Cached because every benchmark run would otherwise construct new
    clients. Imports are local so that importing this module does not
    require an API key.
    """
    from langchain_openai import ChatOpenAI, OpenAIEmbeddings
    from openai import AsyncOpenAI
    from ragas.embeddings import LangchainEmbeddingsWrapper
    from ragas.llms import LangchainLLMWrapper, llm_factory

    judge_chat_model = ChatOpenAI(
        model=JUDGE_MODEL,
        temperature=0,
    )

    judge_embedding_model = OpenAIEmbeddings(
        model=JUDGE_EMBEDDING_MODEL,
    )

    return BenchmarkJudges(
        ragas_llm=LangchainLLMWrapper(
            judge_chat_model
        ),
        ragas_embeddings=LangchainEmbeddingsWrapper(
            judge_embedding_model
        ),
        sql_llm=llm_factory(
            model=JUDGE_MODEL,
            provider="openai",
            client=AsyncOpenAI(),
        ),
        claim_llm=judge_chat_model,
    )

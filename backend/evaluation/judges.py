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


# Override to grade with a different judge; keep it stable across the runs
# you intend to compare.
JUDGE_MODEL = os.getenv(
    "BENCHMARK_JUDGE_MODEL",
    "gpt-5.4-mini",
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


@lru_cache(maxsize=1)
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
    )

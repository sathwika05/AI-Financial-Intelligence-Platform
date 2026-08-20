"""
Which contexts each RAGAS metric is scored against.

The metrics answer two different questions and were being given one context
set. On a MIXED question the reranker returns a handful of document chunks
alongside live market rows, and grading retrieval quality across all of them
measured the market API rather than the document corpus: context_precision
read 0.1186 while retrieval itself was sound.

  retrieval metrics   precision, recall, entity recall   documents only
  generation metrics  faithfulness, relevancy, noise     everything

The generation metrics keep the full set on purpose. Removing a context the
answer legitimately cites would make a grounded claim look unsupported, so
filtering everywhere would trade one wrong number for another.
"""
import inspect

import pytest

from backend.evaluation.benchmark_runner import BenchmarkRunner
from backend.evaluation.evaluators.ragas_evaluator import RagasEvaluator
from backend.evaluation.schemas import PipelineExecution


MIXED_RECORDS = [
    {"source_type": "market", "content": "NVDA: current_price=225.01, pe_ratio=34.4"},
    {"source_type": "market", "content": "MSFT: current_price=480.35"},
    {"source_type": "vector", "content": "ARK increased its Nvidia position."},
    {"source_type": "sql", "content": '{"ticker": "EOG", "pe_ratio": 10.98}'},
    {"source_type": "vector", "content": "Microsoft Teams AI voice agents."},
]


class TestDocumentFilter:
    def test_keeps_only_document_chunks(self):
        out = BenchmarkRunner._document_contexts(MIXED_RECORDS)
        assert out == [
            "ARK increased its Nvidia position.",
            "Microsoft Teams AI voice agents.",
        ]

    def test_market_rows_are_excluded(self):
        out = BenchmarkRunner._document_contexts(MIXED_RECORDS)
        assert not any("current_price" in c for c in out)

    def test_sql_rows_are_excluded(self):
        """
        A SQL result row is evidence, but it is not a retrieved document
        and says nothing about retrieval quality.
        """
        out = BenchmarkRunner._document_contexts(MIXED_RECORDS)
        assert not any("EOG" in c for c in out)

    def test_the_real_proportion(self):
        """
        The run that prompted this: 14 contexts, ~3 of them documents.
        """
        out = BenchmarkRunner._document_contexts(MIXED_RECORDS)
        assert len(out) == 2
        assert len(MIXED_RECORDS) == 5

    def test_empty_input_is_safe(self):
        assert BenchmarkRunner._document_contexts([]) == []

    def test_records_without_a_source_type_are_dropped(self):
        assert BenchmarkRunner._document_contexts(
            [{"content": "untagged"}]
        ) == []

    def test_all_market_yields_nothing(self):
        """
        Triggers the caller's fallback rather than producing an empty
        retrieval sample.
        """
        assert BenchmarkRunner._document_contexts(
            [{"source_type": "market", "content": "x"}]
        ) == []


class TestEvaluatorWiring:
    def test_evaluate_accepts_document_contexts(self):
        params = inspect.signature(RagasEvaluator.evaluate).parameters
        assert "document_contexts" in params
        # Optional, so a caller that does not separate them still works.
        assert params["document_contexts"].default is None

    def test_score_accepts_document_contexts(self):
        params = inspect.signature(RagasEvaluator._score).parameters
        assert "document_contexts" in params

    def test_retrieval_metrics_use_the_retrieval_sample(self):
        """
        The three retrieval metrics must be scored against the filtered
        sample, and the generation metrics against the full one. Asserted
        on source because the alternative is an LLM-backed run.
        """
        src = inspect.getsource(RagasEvaluator._score)

        precision = src.index("context_precision\"] = await")
        recall = src.index("context_recall\"] = await")
        entity = src.index("context_entity_recall\"] = await")

        for name, at in (
            ("precision", precision),
            ("recall", recall),
            ("entity_recall", entity),
        ):
            window = src[at:at + 260]
            assert "retrieval_sample" in window, f"{name} not using retrieval_sample"

    def test_generation_metrics_keep_every_context(self):
        src = inspect.getsource(RagasEvaluator._score)
        head = src[: src.index("context_precision\"] = await")]
        # faithfulness and response_relevancy are scored from `sample`,
        # which is bound to generation_sample.
        assert "sample = generation_sample" in src
        assert "retrieval_sample" not in head.split("retrieval_sample =")[-1].split("sample = generation_sample")[0]

    def test_falls_back_to_all_contexts_when_no_documents(self):
        """
        `document_contexts or contexts` — an empty filter must not leave the
        retrieval metrics scoring against nothing, which would read 0.0 and
        look like a retrieval failure.
        """
        src = inspect.getsource(RagasEvaluator._score)
        assert "document_contexts or contexts" in src


class TestExecutionCarriesRecords:
    def test_pipeline_execution_has_the_typed_records(self):
        """
        reranked_contexts is flattened text; the source_type only survives
        on the records.
        """
        fields = PipelineExecution.model_fields
        assert "reranked_context_records" in fields

    def test_defaults_to_empty(self):
        execution = PipelineExecution(actual_intent="MIXED")
        assert execution.reranked_context_records == []

    def test_records_round_trip(self):
        execution = PipelineExecution(
            actual_intent="MIXED",
            reranked_context_records=MIXED_RECORDS,
        )
        assert (
            BenchmarkRunner._document_contexts(
                execution.reranked_context_records
            )
            == [
                "ARK increased its Nvidia position.",
                "Microsoft Teams AI voice agents.",
            ]
        )

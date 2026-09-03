"""
Assembling the evidence, and producing one question's audit.

THE EVIDENCE IS THE RUN'S OWN
    Document chunks, SQL rows and market rows — whatever this question
    actually retrieved, and nothing else. Not the corpus, not the judge's
    training. A claim that is true of the world but absent from what was
    retrieved is unsupported here, because the system is accountable for
    what it can show.

    SQL rows matter more than they look. A valuation answer's numbers come
    from the database, not from any document, so an audit fed only
    document chunks would mark every correct P/E figure UNSUPPORTED and
    report a catastrophic rate for a route that works perfectly.

WHY SOURCES ARE LABELLED
    The judge is told which evidence is a document and which is a table
    row. "Revenue grew 12%" derived from two SQL columns is a legitimate
    calculation; the same claim pulled from a news headline is not the
    same kind of support, and a human validating the label needs to see
    which happened.
"""
from backend.evaluation.claims.audit import ClaimAudit
from backend.evaluation.claims.extractor import (
    evidence_from,
    parse_candidates,
    split_prompt,
)
from backend.evaluation.claims.runner import audit_answer
from backend.evaluation.schemas import PipelineExecution


def execution(**kwargs) -> PipelineExecution:
    return PipelineExecution(**kwargs)


class TestEvidenceAssembly:
    def test_document_chunks_are_included(self):
        evidence = evidence_from(
            execution(reranked_contexts=["NVDA revenue rose 12% in Q3."])
        )

        assert any("revenue rose 12%" in item for item in evidence)

    def test_sql_rows_are_included(self):
        """
        The numbers in a valuation answer come from here, not from any
        document. Omitting them marks every correct figure UNSUPPORTED.
        """
        evidence = evidence_from(
            execution(sql_rows=[{"ticker": "ADBE", "pe_ratio": 24.1}])
        )

        assert any("ADBE" in item and "24.1" in item for item in evidence)

    def test_market_rows_are_included(self):
        evidence = evidence_from(
            execution(market_result={"NVDA": {"price": 178.2}})
        )

        assert any("178.2" in item for item in evidence)

    def test_each_item_names_its_source(self):
        """
        A figure derived from two SQL columns is a calculation; the same
        figure from a headline is not the same kind of support.
        """
        evidence = evidence_from(
            execution(
                reranked_contexts=["a document chunk"],
                sql_rows=[{"ticker": "ADBE"}],
            )
        )
        joined = " ".join(evidence).lower()

        assert "document" in joined
        assert "sql" in joined

    def test_reranked_contexts_are_preferred_over_raw_retrieved(self):
        """
        The reranked set is what the analysis node actually saw. Auditing
        against the pre-rerank list would grade the answer on evidence it
        was never shown.
        """
        evidence = evidence_from(
            execution(
                retrieved_contexts=["discarded by the reranker"],
                reranked_contexts=["what analysis actually read"],
            )
        )
        joined = " ".join(evidence)

        assert "what analysis actually read" in joined
        assert "discarded by the reranker" not in joined

    def test_raw_contexts_are_used_when_nothing_was_reranked(self):
        """Baseline runs have no reranker, and still need evidence."""
        evidence = evidence_from(
            execution(retrieved_contexts=["the only contexts there are"])
        )

        assert any("only contexts" in item for item in evidence)

    def test_an_empty_execution_yields_no_evidence(self):
        assert evidence_from(execution()) == []


class TestSplittingTheAnswer:
    def test_the_answer_reaches_the_prompt(self):
        prompt = split_prompt("Revenue grew 12%. Margins improved.")

        assert "Revenue grew 12%" in prompt

    def test_the_prompt_asks_for_atomic_assertions(self):
        lowered = split_prompt("some answer").lower()

        assert "atomic" in lowered or "single" in lowered

    def test_the_prompt_forbids_inventing_content(self):
        """
        A splitter that paraphrases produces claims the answer never made,
        and the audit then scores something nobody wrote.
        """
        lowered = split_prompt("some answer").lower()

        assert "verbatim" in lowered or "do not" in lowered

    def test_candidates_are_read_back(self):
        raw = '{"claims": ["Revenue grew 12%.", "Margins improved."]}'

        assert parse_candidates(raw) == [
            "Revenue grew 12%.",
            "Margins improved.",
        ]

    def test_json_wrapped_in_prose_is_still_read(self):
        raw = 'Sure:\n```json\n{"claims": ["Revenue grew 12%."]}\n```'

        assert parse_candidates(raw) == ["Revenue grew 12%."]

    def test_unreadable_output_yields_nothing_rather_than_raising(self):
        """
        A split failure means no claims were measured. That has to be
        distinguishable from an answer with no claims — the caller records
        zero, and zero claims is never a perfect score.
        """
        assert parse_candidates("the model was unwell") == []


class TestAuditingOneAnswer:
    ANSWER = (
        "Revenue grew 12% year over year. Margins improved significantly. "
        "NVDA may benefit from continued AI demand."
    )

    async def _audit(self, answer=None, exec_=None):
        async def splitter(_prompt):
            return (
                '{"claims": ['
                '"Revenue grew 12% year over year.",'
                '"Margins improved significantly.",'
                '"NVDA may benefit from continued AI demand."]}'
            )

        async def judge(_prompt):
            return (
                '{"verdicts": ['
                '{"index": 0, "label": "SUPPORTED", "reasoning": "50.0 to 56.0 is 12%."},'
                '{"index": 1, "label": "UNSUPPORTED", "reasoning": "No margin data."}]}'
            )

        return await audit_answer(
            answer=answer if answer is not None else self.ANSWER,
            execution=exec_ or execution(
                reranked_contexts=["NVDA revenue rose from $50.0B to $56.0B."]
            ),
            splitter=splitter,
            judge=judge,
            evaluator_model="gpt-4o-mini",
        )

    async def test_it_returns_an_audit(self):
        assert isinstance(await self._audit(), ClaimAudit)

    async def test_the_hedge_is_dropped_not_scored(self):
        audit = await self._audit()

        assert audit.total_claims == 2
        assert audit.dropped_count == 1

    async def test_labels_are_applied_to_the_right_claims(self):
        audit = await self._audit()

        assert audit.claims[0].label == "SUPPORTED"
        assert audit.claims[1].label == "UNSUPPORTED"

    async def test_the_intensifier_is_stripped_in_the_checked_text(self):
        audit = await self._audit()

        assert audit.claims[1].claim == "Margins improved."
        assert audit.claims[1].original == "Margins improved significantly."

    async def test_the_evidence_is_stored_on_each_claim(self):
        """
        The validation page shows evidence beside the claim, and
        PipelineExecution is never persisted — so it has to live here.
        """
        audit = await self._audit()

        assert any("50.0B" in item for item in audit.claims[0].evidence)

    async def test_the_judge_is_recorded(self):
        audit = await self._audit()

        assert audit.claims[0].evaluator_model == "gpt-4o-mini"

    async def test_an_empty_answer_produces_an_empty_audit(self):
        audit = await self._audit(answer="")

        assert audit.total_claims == 0
        assert audit.dropped_count == 0

    async def test_no_evidence_makes_every_claim_insufficient(self):
        audit = await self._audit(exec_=execution())

        assert audit.insufficient_evidence == audit.total_claims
        assert audit.total_claims == 2

    async def test_a_splitter_failure_does_not_raise(self):
        """The audit is additional; a failure must not fail the question."""
        async def splitter(_prompt):
            raise RuntimeError("splitter is down")

        async def judge(_prompt):
            raise AssertionError("should not be reached")

        audit = await audit_answer(
            answer=self.ANSWER,
            execution=execution(reranked_contexts=["evidence"]),
            splitter=splitter,
            judge=judge,
            evaluator_model="gpt-4o-mini",
        )

        assert audit.total_claims == 0

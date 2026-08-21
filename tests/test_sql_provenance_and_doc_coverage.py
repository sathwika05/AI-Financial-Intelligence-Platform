"""
Two defects that a passing benchmark concealed.

1. execute_sql_query repairs a failed query in place and returns the
   repaired query's rows. Only the rows came back, so state kept the
   original. The SQL evaluator then graded two different queries at once:
   sql_accuracy scored the execution that worked, sql_equivalence scored a
   query that does not parse, and valuation_002 reported 1.0 on both while
   its recorded SQL referenced c.eps, a column `companies` does not have.

2. The reranker's coverage floor counted evidence of any source, so a
   company holding one SQL row and one market row was already covered and
   its document was never pulled back in. mixed_001's pool held five
   documents, one per cohort company, and the selection kept one.
"""
import inspect

import pytest

from backend.nodes.sql_node import capture_sql_tool_outputs
from backend.nodes import reranker_node as rn


class _ToolMessage:
    """Minimal stand-in; capture_sql_tool_outputs only reads name/content."""

    def __init__(self, name, content):
        self.name = name
        self.content = content


@pytest.fixture(autouse=True)
def _patch_tool_message(monkeypatch):
    monkeypatch.setattr(
        "backend.nodes.sql_node.ToolMessage",
        _ToolMessage,
    )


class TestSQLProvenance:
    def test_executed_sql_overrides_the_generated_one(self):
        """The repaired query is what state must carry."""
        broken = "SELECT c.eps FROM companies c"
        fixed = "SELECT fm.eps FROM financial_metrics fm"

        state = {
            "messages": [
                _ToolMessage("generate_sql_query", f'{{"sql": "{broken}"}}'),
                _ToolMessage(
                    "execute_sql_query",
                    '{"columns": ["eps"], "rows": [], "row_count": 0, '
                    f'"error": null, "executed_sql": "{fixed}"}}',
                ),
            ]
        }

        updates = capture_sql_tool_outputs(state)
        assert updates["last_sql"] == fixed
        assert updates["last_sql"] != broken

    def test_generated_sql_is_kept_when_nothing_was_repaired(self):
        """
        The common path: the query ran as written, and executed_sql equals
        it. No behaviour change for queries that never failed.
        """
        query = "SELECT ticker FROM companies"

        state = {
            "messages": [
                _ToolMessage("generate_sql_query", f'{{"sql": "{query}"}}'),
                _ToolMessage(
                    "execute_sql_query",
                    '{"columns": [], "rows": [], "row_count": 0, '
                    f'"error": null, "executed_sql": "{query}"}}',
                ),
            ]
        }

        assert capture_sql_tool_outputs(state)["last_sql"] == query

    def test_missing_executed_sql_does_not_erase_the_generated_one(self):
        """An older payload without the field must not blank last_sql."""
        query = "SELECT ticker FROM companies"

        state = {
            "messages": [
                _ToolMessage("generate_sql_query", f'{{"sql": "{query}"}}'),
                _ToolMessage(
                    "execute_sql_query",
                    '{"columns": [], "rows": [], "row_count": 0, "error": null}',
                ),
            ]
        }

        assert capture_sql_tool_outputs(state)["last_sql"] == query

    def test_run_select_reports_the_query_it_ran(self):
        from backend.retrieval import sql_executor

        src = inspect.getsource(sql_executor._run_select)
        assert '"executed_sql": query' in src

    def test_auto_fix_marks_the_payload(self):
        from backend.retrieval import sql_executor

        # execute_sql_query is a StructuredTool; the body is on .coroutine.
        src = inspect.getsource(sql_executor.execute_sql_query.coroutine)
        assert 'payload["auto_fixed"] = True' in src
        assert 'payload["original_sql"] = query' in src


def _company(ticker):
    return {"ticker": ticker, "name": ticker}


def _cand(cid, ticker, source_type, score=0.5):
    return {
        "candidate_id": cid,
        "ticker": ticker,
        "name": ticker,
        "source_type": source_type,
        "content": f"{ticker} {source_type} content",
        "original_score": score,
    }


class TestDocumentCoverageFloor:
    def test_document_is_backfilled_when_sql_and_market_already_cover(self):
        """
        The exact mixed_001 shape: every company covered twice over by
        non-document evidence, its document sitting unselected.
        """
        companies = [_company("NVDA"), _company("AMD")]

        candidates = [
            _cand(0, "NVDA", "sql"),
            _cand(1, "NVDA", "market"),
            _cand(2, "NVDA", "vector", 0.1),
            _cand(3, "AMD", "sql"),
            _cand(4, "AMD", "market"),
            _cand(5, "AMD", "vector", 0.1),
        ]

        selected = [c for c in candidates if c["source_type"] != "vector"]

        out = rn._apply_coverage_floors(
            selected=list(selected),
            candidates=candidates,
            target_companies=companies,
            min_per_company=2,
            min_documents_per_company=1,
        )

        docs = [r for r in out if r["source_type"] == "vector"]
        assert len(docs) == 2
        assert {d["ticker"] for d in docs} == {"NVDA", "AMD"}

    def test_a_company_with_no_document_is_not_invented(self):
        """Absence in the pool stays absence — nothing is substituted."""
        companies = [_company("NVDA"), _company("GOOGL")]

        candidates = [
            _cand(0, "NVDA", "sql"),
            _cand(1, "NVDA", "vector", 0.1),
            _cand(2, "GOOGL", "sql"),
        ]

        out = rn._apply_coverage_floors(
            selected=[candidates[0], candidates[2]],
            candidates=candidates,
            target_companies=companies,
            min_per_company=1,
            min_documents_per_company=1,
        )

        docs = [r for r in out if r["source_type"] == "vector"]
        assert [d["ticker"] for d in docs] == ["NVDA"]

    def test_an_existing_document_is_not_duplicated(self):
        companies = [_company("NVDA")]

        candidates = [
            _cand(0, "NVDA", "sql"),
            _cand(1, "NVDA", "vector", 0.9),
        ]

        out = rn._apply_coverage_floors(
            selected=list(candidates),
            candidates=candidates,
            target_companies=companies,
            min_per_company=1,
            min_documents_per_company=1,
        )

        assert len([r for r in out if r["source_type"] == "vector"]) == 1

    def test_source_filter_off_preserves_the_old_behaviour(self):
        """
        Without source_type the floor counts any evidence, which is what
        the general pass still relies on.
        """
        companies = [_company("NVDA")]
        candidates = [_cand(0, "NVDA", "sql"), _cand(1, "NVDA", "market")]

        out = rn._backfill_company_coverage(
            selected=[candidates[0]],
            candidates=candidates,
            target_companies=companies,
            min_per_company=2,
        )

        assert len(out) == 2

    def test_the_constant_is_wired_into_the_node(self):
        src = inspect.getsource(rn.reranker_node)
        assert "min_documents_per_company=MIN_DOCUMENTS_PER_COMPANY" in src
        assert rn.MIN_DOCUMENTS_PER_COMPANY >= 1

    def test_prompt_tells_the_model_about_documents(self):
        src = inspect.getsource(rn.rerank_hybrid_contexts)
        assert "min_documents_per_company" in src
        normalized = " ".join(src.split())
        assert "cannot substitute for them" in normalized


class TestVectorBudgetScalesWithCohort:
    """
    A fixed top_k of five is a per-question budget spent on a per-company
    job. sentiment_001 compares three companies and returned five chunks
    from a cohort holding twelve, so a company could contribute nothing and
    the comparison rested on whichever chunks ranked highest. "Which company
    has the most positive coverage" is unanswerable for a company with no
    retrieved coverage.
    """

    def test_budget_widens_for_a_multi_company_filter(self):
        from backend.retrieval import vector_search

        src = inspect.getsource(vector_search.search_similar_chunks)
        assert "CHUNKS_PER_COMPANY * len(company_ids)" in src
        assert vector_search.CHUNKS_PER_COMPANY >= 2

    def test_it_only_widens_never_narrows(self):
        """
        max() against the caller's value, so an unfiltered query keeps the
        top_k it asked for and a single-company filter is not cut down.
        """
        from backend.retrieval import vector_search

        src = inspect.getsource(vector_search.search_similar_chunks)
        block = src[src.index("if company_ids:"): src.index("fetch_k =")]
        assert "max(" in block
        assert "top_k," in block

    def test_no_filter_leaves_the_budget_alone(self):
        from backend.retrieval import vector_search

        src = inspect.getsource(vector_search.search_similar_chunks)
        assert 'get("company_ids") or []' in src
        # Guarded, so an empty filter cannot produce top_k = 0.
        assert "if company_ids:" in src


class TestSchemaOwnershipRule:
    """
    The generator knew "profitable" means eps > 0 — rule 4 says so and uses
    valuation_002's own wording as its example — but nothing told it which
    table eps belongs to. It guessed twice and got it wrong both ways:
    `WHERE c.eps > 0`, which PostgreSQL rejects, and then dropping the
    filter entirely, which executes and answers a different question.

    The auto-fixer rescued the first into a reported 1.0, so this only
    became visible once the evaluator started grading the query that ran.
    """

    def _prompt(self):
        from backend.retrieval import sql_executor

        # generate_sql_query is a StructuredTool; the body is on .func.
        tool = sql_executor.generate_sql_query
        src = inspect.getsource(getattr(tool, "func", tool))
        return " ".join(src.split())

    def test_it_names_the_table_the_measures_live_on(self):
        prompt = self._prompt()
        assert "companies c.market_cap" in prompt
        assert "financial_metrics fm.eps, fm.pe_ratio, fm.revenue_growth" in prompt

    def test_it_states_the_join(self):
        prompt = self._prompt()
        assert "JOIN financial_metrics fm ON fm.company_id = c.id" in prompt

    def test_it_names_the_columns_that_do_not_exist(self):
        prompt = self._prompt()
        assert "c.eps, c.pe_ratio and c.revenue_growth do not exist" in prompt

    def test_the_rule_covers_both_directions(self):
        """
        The first version of this rule named only one side — that eps lives
        on financial_metrics — and the model over-corrected, moving
        market_cap there too. mixed_001 needs c.market_cap and fm.pe_ratio
        in the same query, so it is the question that exercises both halves,
        and it failed with "column fm.market_cap does not exist".
        """
        prompt = self._prompt()
        assert "neither does fm.market_cap" in prompt
        assert "needs both tables" in prompt

    def test_it_forbids_dropping_the_condition_as_the_workaround(self):
        """
        The silent failure is worse than the loud one: a dropped filter
        executes and answers a different question.
        """
        prompt = self._prompt()
        assert "never drop the condition to make the query run" in prompt


class TestCountIsNotADistractor:
    """
    growth_cheap_30 asked "Which five companies combine revenue growth above
    10% with a P/E ratio below 30?" and the generator answered with LIMIT 10,
    taking its count from the filter threshold instead of from the question.
    The rows and their order were right — the ranking evaluator matched all
    five — so only the row count was wrong, and sql_accuracy read 0.6667.

    It was the one genuine failure across 62 SQL questions, and it needed a
    question carrying numeric distractors to surface at all.
    """

    def _prompt(self):
        from backend.retrieval import sql_executor

        tool = sql_executor.generate_sql_query
        src = inspect.getsource(getattr(tool, "func", tool))
        return " ".join(src.split())

    def test_it_warns_that_filter_numbers_are_not_the_count(self):
        prompt = self._prompt()
        assert "OTHER NUMBERS IN THE QUESTION ARE NOT THE COUNT" in prompt

    def test_it_carries_the_failing_example(self):
        prompt = self._prompt()
        assert "The 10 belongs to `revenue_growth > 0.10`" in prompt

    def test_it_says_where_the_count_attaches(self):
        prompt = self._prompt()
        assert "the number attached to the thing being returned" in prompt

    def test_it_covers_a_count_stated_before_the_conditions(self):
        prompt = self._prompt()
        assert "A count stated early still governs the LIMIT" in prompt

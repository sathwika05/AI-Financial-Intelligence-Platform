"""
"SQL returned something" is a question about rows, not about prose.

    has_sql = sql_result is not None and bool(sql_result.get("answer"))

`answer` is the SQL agent's last message -- natural language it wrote for
a human. When the query matches nothing the agent still answers, with a
sentence like "No companies matched your criteria", and a sentence is a
non-empty string. So has_sql was True for a branch that found nothing.

That matters because has_sql decides how much weight the valuation and
growth dimensions carry (get_dynamic_weights), so an empty SQL branch was
weighted as though it had succeeded, and the composite was normalised
against a contribution that did not exist.

The structured result is already there. run_sql_retrieval returns
db_result alongside answer, and extract_sql_rows already normalises every
shape it comes in. Counting rows is exact, and unaffected by how the
model chose to phrase a failure.

SEPARATE FROM confidence
    hybrid_retrieval sets `0.9 if "No companies" not in answer else 0.1`
    from the same prose. Same root cause, different consumer, and that one
    feeds a number that is computed and then discarded -- so it is fixed
    with the confidence work rather than here.
"""
from __future__ import annotations

import pytest

from backend.scoring.ranker import sql_returned_rows


class TestRowsDecideIt:
    def test_rows_present_is_available(self):
        assert sql_returned_rows(
            {"answer": "Here are five companies", "db_result": {
                "data": [{"ticker": "HON"}, {"ticker": "PYPL"}]
            }}
        ) is True

    def test_no_rows_is_not_available(self):
        assert sql_returned_rows(
            {"answer": "No companies matched your criteria",
             "db_result": {"data": []}}
        ) is False

    @pytest.mark.parametrize(
        "answer",
        [
            "no companies matched",
            "I couldn't find any companies",
            "There are none that meet those filters",
            "No companies matched your criteria",
        ],
        ids=["lowercase", "different wording", "no such word", "exact"],
    )
    def test_phrasing_cannot_change_the_answer(self, answer):
        """
        The bug being fixed: only the exact string "No companies" was
        recognised, so three of these four scored as a success.
        """
        assert sql_returned_rows(
            {"answer": answer, "db_result": {"data": []}}
        ) is False


class TestTheShapesItArrivesIn:
    @pytest.mark.parametrize(
        "db_result",
        [
            {"rows": [{"t": "HON"}]},
            {"data": [{"t": "HON"}]},
            {"results": [{"t": "HON"}]},
            [{"t": "HON"}],
        ],
        ids=["rows", "data", "results", "bare list"],
    )
    def test_every_row_shape_counts(self, db_result):
        assert sql_returned_rows(
            {"answer": "x", "db_result": db_result}
        ) is True

    def test_an_error_is_not_a_result(self):
        assert sql_returned_rows(
            {"answer": "Query failed",
             "db_result": {"data": [], "error": "syntax error"}}
        ) is False

    def test_rows_alongside_an_error_are_not_trusted(self):
        """
        A partial result from a failed execution is not a result.
        """
        assert sql_returned_rows(
            {"answer": "x",
             "db_result": {"data": [{"t": "HON"}], "error": "timeout"}}
        ) is False


class TestTheAbsentCases:
    @pytest.mark.parametrize(
        "sql_result", [None, {}, {"answer": "x"}],
        ids=["no result", "empty", "no db_result"],
    )
    def test_nothing_to_read_is_not_available(self, sql_result):
        assert sql_returned_rows(sql_result) is False


class TestTheRankerUsesIt:
    def test_has_sql_is_computed_from_rows(self):
        import inspect

        from backend.scoring import ranker

        source = inspect.getsource(ranker.rerank)

        assert "sql_returned_rows(" in source
        assert 'bool(sql_result.get("answer"))' not in source, (
            "the prose check is what this replaces"
        )

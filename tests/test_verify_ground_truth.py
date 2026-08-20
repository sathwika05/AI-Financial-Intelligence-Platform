"""
The reseed guard.

Ground truth drifts silently: fundamentals move so a "top five" changes
membership, and documents are replaced so a verbatim reference context
vanishes. Neither raises — the pipeline answers correctly and the benchmark
marks it wrong. Both have happened here, which is why this check exists and
why it exits non-zero.
"""
import inspect

from backend.evaluation.datasets import verify_ground_truth as vgt


class TestNumericComparison:
    def test_int_and_float_compare_equal(self):
        """
        market_cap is double precision and goldens have been written both
        ways; a stale-data check must not fire on 10 versus 10.0.
        """
        assert vgt._comparable(10) == vgt._comparable(10.0)

    def test_bool_is_not_widened_to_int(self):
        """
        bool subclasses int, so a bare True compares equal to 1.0. Returning
        it unchanged is not enough — it has to be tagged.
        """
        assert vgt._comparable(True) != vgt._comparable(1)
        assert vgt._comparable(False) != vgt._comparable(0)
        assert vgt._comparable(True) == vgt._comparable(True)

    def test_strings_are_left_alone(self):
        assert vgt._comparable("10") == "10"
        assert vgt._comparable("10") != vgt._comparable(10)

    def test_row_widens_every_cell(self):
        assert vgt._row({"a": 1, "b": "x"}) == {"a": 1.0, "b": "x"}


class TestChecksArePresent:
    def test_it_checks_rows_rankings_contexts_and_limits(self):
        src = inspect.getsource(vgt.verify)
        assert "expected_sql_result is stale" in src
        assert "expected_ranking disagrees" in src
        assert "absent from" in src
        assert "non-binding" in src

    def test_drift_fails_but_weakness_does_not(self):
        """
        A stale row is wrong and gates the run. A non-binding LIMIT is a
        weak test, not a wrong one, so it warns and exits zero.
        """
        src = inspect.getsource(vgt.verify)
        limit_block = src[src.index("non-binding") - 400: src.index("non-binding")]
        assert "warnings.append" in limit_block
        assert "return 1" in src
        assert "if problems:" in src

    def test_nothing_is_written_back(self):
        """
        A mismatch needs a person to decide whether the question or the
        ground truth changed, so this never rewrites question_sets.py.
        """
        src = inspect.getsource(vgt)
        assert "question_sets.py" not in src.replace(
            "re-read the contexts", ""
        ) or "open(" not in src

    def test_sqlalchemy_url_is_normalized_for_asyncpg(self):
        src = inspect.getsource(vgt._connect)
        assert "postgresql+asyncpg://" in src
        assert "postgresql+psycopg2://" in src

    def test_order_requirement_none_skips_the_ranking_check(self):
        """
        mixed_001 is sql_order_requirement="none" — SQL cannot produce the
        ranking the question asks for, so row order is not gradable and the
        ranking check must not fire on it.
        """
        src = inspect.getsource(vgt.verify)
        assert 'sql_order_requirement != "none"' in src

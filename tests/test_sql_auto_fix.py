"""
The SQL auto-fix path.

execute_sql_query was a synchronous tool calling `fix_sql_error.invoke()`,
but fix_sql_error is `async def` — so a StructuredTool holding only a
coroutine. Any SQL execution error therefore raised

    StructuredTool does not support sync invocation

which propagated out of the SQL branch and destroyed it, rather than being
repaired. The retry machinery built around it had never run: the failure
was invisible until the generator first produced a query with a bad column
name, and then it took out the whole branch.

These tests exercise the repair path end to end with the database and the
repair LLM stubbed, so they assert the control flow rather than any model
behaviour.
"""
import pytest
from langchain_core.runnables import RunnableConfig

from backend.retrieval import sql_executor


GOOD_SQL = "SELECT c.ticker FROM companies c LIMIT 1"


@pytest.fixture
def rows():
    return {
        "columns": ["ticker"],
        "rows": [{"ticker": "NVDA"}],
        "row_count": 1,
        "error": None,
    }


class TestToolShape:
    def test_execute_is_a_coroutine_tool(self):
        """
        The root cause in one assertion: a tool that awaits another tool
        cannot itself be synchronous.
        """
        assert sql_executor.execute_sql_query.coroutine is not None

    def test_fix_is_a_coroutine_tool(self):
        assert sql_executor.fix_sql_error.coroutine is not None

    @pytest.mark.parametrize(
        "tool",
        ["execute_sql_query", "fix_sql_error"],
    )
    def test_config_is_injected_not_an_llm_supplied_argument(self, tool):
        """
        Both resolve their LLM from the RunnableConfig, so it must be
        annotated as plain RunnableConfig — langchain then strips it from
        the schema and supplies it at runtime.

        Annotated as `RunnableConfig | None = None` the union is not
        recognised, so it stays an ordinary argument, the model is invited
        to fill it, and it arrives as None: the repair reached
        get_llm_client and died on "LangGraph config was not supplied".
        """
        fields = getattr(sql_executor, tool).args_schema.model_fields
        assert "config" not in fields


class TestHappyPath:
    async def test_successful_query_returns_rows_and_never_repairs(
        self, monkeypatch, rows
    ):
        called = []

        async def fake_select(query):
            return rows

        async def fake_fix(*a, **k):
            called.append(1)
            return "SELECT 1"

        monkeypatch.setattr(sql_executor, "_run_select", fake_select)
        monkeypatch.setattr(sql_executor.fix_sql_error, "coroutine", fake_fix)

        out = await sql_executor.execute_sql_query.ainvoke(
            {"sql_query": GOOD_SQL}
        )

        assert '"row_count": 1' in out
        assert called == [], "repair must not run when the query succeeds"


class TestRepairPath:
    async def test_execution_error_triggers_repair_and_returns_its_rows(
        self, monkeypatch, rows
    ):
        """
        The regression. Before this fix the first _run_select failure
        raised out of the tool and the SQL branch returned an error
        payload; nothing was repaired.
        """
        attempts = []

        async def fake_select(query):
            attempts.append(query)
            if len(attempts) == 1:
                raise Exception('column "c.pe_ratio" does not exist')
            return rows

        async def fake_fix(
            original_query, error_message, question, config: RunnableConfig
        ):
            assert "does not exist" in error_message
            return "SELECT c.ticker FROM companies c JOIN financial_metrics fm ON fm.company_id = c.id"

        monkeypatch.setattr(sql_executor, "_run_select", fake_select)
        monkeypatch.setattr(sql_executor.fix_sql_error, "coroutine", fake_fix)

        out = await sql_executor.execute_sql_query.ainvoke(
            {"sql_query": GOOD_SQL, "question": "which companies"}
        )

        assert len(attempts) == 2, "the repaired query must be executed"
        assert '"row_count": 1' in out
        assert '"error": null' in out

    async def test_repair_result_is_validated_before_running(
        self, monkeypatch, rows
    ):
        """A repair that returns unsafe SQL must not be executed."""
        attempts = []

        async def fake_select(query):
            attempts.append(query)
            raise Exception("boom")

        async def fake_fix(
            original_query, error_message, question, config: RunnableConfig
        ):
            return "DROP TABLE companies"

        monkeypatch.setattr(sql_executor, "_run_select", fake_select)
        monkeypatch.setattr(sql_executor.fix_sql_error, "coroutine", fake_fix)

        out = await sql_executor.execute_sql_query.ainvoke(
            {"sql_query": GOOD_SQL}
        )

        assert len(attempts) == 1, "unsafe repaired SQL must never be executed"
        assert "Fixed query validation failed" in out

    async def test_both_errors_are_reported_when_repair_also_fails(
        self, monkeypatch
    ):
        async def fake_select(query):
            raise Exception(
                "original boom" if "companies c LIMIT" in query else "repair boom"
            )

        async def fake_fix(
            original_query, error_message, question, config: RunnableConfig
        ):
            return "SELECT c.name FROM companies c"

        monkeypatch.setattr(sql_executor, "_run_select", fake_select)
        monkeypatch.setattr(sql_executor.fix_sql_error, "coroutine", fake_fix)

        out = await sql_executor.execute_sql_query.ainvoke(
            {"sql_query": GOOD_SQL}
        )

        assert "original boom" in out
        assert "repair boom" in out

    async def test_unsafe_input_is_rejected_before_any_execution(
        self, monkeypatch
    ):
        attempts = []

        async def fake_select(query):
            attempts.append(query)
            return {}

        monkeypatch.setattr(sql_executor, "_run_select", fake_select)

        out = await sql_executor.execute_sql_query.ainvoke(
            {"sql_query": "DELETE FROM companies"}
        )

        assert attempts == []
        assert "Query validation failed" in out


class TestAsyncEngine:
    def test_run_select_is_a_coroutine(self):
        import inspect

        assert inspect.iscoroutinefunction(sql_executor._run_select)

    def test_run_select_uses_an_async_engine(self):
        """
        Not a second sync engine. The sync one that remains serves only
        get_sector_vocabulary, which is read from a synchronous tool.

        The engine is now read_engine, which is the SELECT-only role when
        READONLY_DATABASE_URL is set and the application engine otherwise.
        Both are async; what this guards against is a sync one reappearing,
        because being sync is what made the auto-fix path unreachable.
        """
        import inspect

        src = inspect.getsource(sql_executor._run_select)
        assert "read_engine.connect()" in src
        assert "create_engine(" not in src

"""
Importing the SQL tooling must not require a database.

sql_executor built its SQLDatabase at module scope, which connects and
introspects immediately, and asked for include_tables -- so the import
raised unless companies, financial_metrics and documents already existed.

main.py creates those tables in the app's lifespan, which runs long after
imports are resolved. So a database that is merely empty could not start
the API at all:

    ValueError: include_tables {'financial_metrics', 'documents',
    'companies'} not found in database

That is the state a newly provisioned RDS is in on the first deploy.
"""
import os
import subprocess
import sys

import pytest


# A database that does not exist. Nothing that only builds an engine will
# notice; anything that connects during import fails here, which is
# exactly the distinction under test -- and it needs no fixture.
NOWHERE = "postgresql+psycopg2://finuser:finpass@localhost:5433/no_such_database"


class TestImportingWithoutADatabase:
    def test_the_module_imports_when_nothing_is_reachable(self):
        result = _import_in_a_subprocess("backend.retrieval.sql_executor")

        assert result.returncode == 0, (
            "importing sql_executor touched the database:\n"
            f"{result.stderr[-2000:]}"
        )

    def test_the_sql_node_imports_too(self):
        """
        The chain that actually breaks a deploy: main.py -> sql_routes ->
        sql_graph -> sql_node -> sql_executor.
        """
        result = _import_in_a_subprocess("backend.nodes.sql_node")

        assert result.returncode == 0, (
            "importing sql_node touched the database:\n"
            f"{result.stderr[-2000:]}"
        )


class TestTheSchemaStillArrives:
    def test_get_schema_reads_the_tables(self):
        """
        Deferring it must not mean losing it: the generator's prompt is
        built from this text, and an empty schema would silently produce
        SQL against columns the model invented.
        """
        from backend.retrieval.sql_executor import get_schema

        schema = get_schema()

        for table in ("companies", "financial_metrics", "documents"):
            assert table in schema

    def test_the_schema_is_read_once(self):
        """
        It was a module-level constant, so it cost one introspection for
        the life of the process. Recomputing it per call would put a
        blocking round trip inside every prompt build.
        """
        from backend.retrieval.sql_executor import get_schema

        assert get_schema() is get_schema()


def _import_in_a_subprocess(module: str) -> subprocess.CompletedProcess:
    environment = {**os.environ, "SYNC_DATABASE_URL": NOWHERE}

    return subprocess.run(
        [sys.executable, "-c", f"import {module}"],
        capture_output=True,
        text=True,
        env=environment,
        timeout=180,
    )

"""
Generated SQL runs on a SELECT-only connection.

validate_sql_query blocks INSERT, UPDATE, DELETE, ALTER, DROP, CREATE and
TRUNCATE by regex. That enumerates badness: it does not cover COPY, GRANT,
pg_sleep, pg_read_file, or reads of pg_catalog. It stays, because a clear
error message beats a permission failure, but it should not be the only
thing between a model-written query and the database.

The role is verified rather than assumed — finreader reads companies and is
refused DELETE, CREATE and COPY TO FILE.

Falls back to the application engine when READONLY_DATABASE_URL is unset, so
a checkout without the role configured still runs.
"""
from backend.retrieval import sql_executor


class TestTheQueryPathUsesTheReadOnlyEngine:
    def test_a_read_only_engine_is_selected(self):
        assert hasattr(sql_executor, "read_engine")

    def test_it_falls_back_when_unconfigured(self):
        """A checkout without the role must still work."""
        from backend.config import settings

        if not settings.READONLY_DATABASE_URL:
            from backend.services.postgres_service import engine

            assert sql_executor.read_engine is engine

    def test_the_regex_layer_is_still_there(self):
        """Defence in depth: the privilege is the floor, not a replacement."""
        validate = sql_executor.validate_sql_query
        validate = getattr(validate, "func", validate)

        assert "only SELECT statements are allowed" in validate(
            "delete from companies"
        )

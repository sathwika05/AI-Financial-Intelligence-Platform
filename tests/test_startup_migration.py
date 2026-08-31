"""
What the container does to the database before it serves a request.

This project has two writers to the schema: SQLAlchemy's create_all, which
runs in the app's lifespan and builds every table from the current models,
and Alembic, whose chain starts at "add embedding column to documents" and
assumes the base tables are already there.

That split means `alembic upgrade head` is only correct on a database
Alembic has seen before. Run it against a database create_all built, and
the first revision fails on a column that already exists; run it against an
empty one, and it fails on a table that does not exist yet. Either way the
API never starts, because the migration and the server are chained with &&.
"""
import pytest


class TestChoosingWhatToDo:
    def test_a_database_alembic_has_seen_is_upgraded(self):
        """The normal case: a version table means the chain applies."""
        from backend.startup_migration import plan_migration

        assert plan_migration(has_alembic_version=True) == "upgrade"

    def test_a_database_alembic_has_never_seen_is_stamped(self):
        """
        No version table means nothing here was built by a migration, so the
        schema came from the models and already matches head. Replaying the
        chain over it would fail on the first ALTER.
        """
        from backend.startup_migration import plan_migration

        assert plan_migration(has_alembic_version=False) == "stamp"


class TestWhereItMigrates:
    def test_the_environment_wins_over_alembic_ini(self):
        """
        alembic.ini hardcodes a developer's localhost URL. In a container
        that is not a database, it is the host loopback -- which is why the
        first attempt at this connected to nothing.
        """
        import os
        from unittest.mock import patch

        from alembic.config import Config

        from backend.startup_migration import configured

        with patch.dict(os.environ, {"SYNC_DATABASE_URL": "postgresql://x/y"}):
            config = configured(Config("alembic.ini"))

        assert config.get_main_option("sqlalchemy.url") == "postgresql://x/y"

    def test_without_an_environment_url_the_ini_is_left_alone(self):
        import os
        from unittest.mock import patch

        from alembic.config import Config

        from backend.startup_migration import configured

        with patch.dict(os.environ, {}, clear=True):
            config = configured(Config("alembic.ini"))

        assert "localhost" in config.get_main_option("sqlalchemy.url")

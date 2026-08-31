"""
Bring the database to the current schema, then get out of the way.

Run by the API container before uvicorn:

    uv run python -m backend.startup_migration

Only the API does this. The worker runs the same image with its own
command, and two tasks racing on the same revision is how you get a
half-applied migration.

Why this is not just `alembic upgrade head`
-------------------------------------------
Two things write this schema. SQLAlchemy's create_all runs in the app's
lifespan and builds every table from the current models. Alembic's chain
starts at "add embedding column to documents" -- it alters the base tables
rather than creating them, because when it was started those tables already
existed.

So `alembic upgrade head` is only right on a database Alembic has already
seen. Against a schema create_all built, the first revision fails on a
column that is already there; against an empty database, it fails on a
table that is not there yet. Either ending leaves the API dead, because the
container chains the migration and the server with && on purpose.

The version table is what tells the two apart, and its absence is
meaningful: nothing in this database was built by a migration, so its
schema came from the models and is by definition already at head. Stamp it
and let create_all fill in anything missing.
"""
from __future__ import annotations

import logging
import os

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect


logger = logging.getLogger(__name__)

ALEMBIC_INI = "alembic.ini"
VERSION_TABLE = "alembic_version"


def plan_migration(*, has_alembic_version: bool) -> str:
    """
    Upgrade a database Alembic has seen; stamp one it has not.

    Kept apart from the running of it so the decision can be read and
    tested without a database, because the two outcomes are hard to tell
    apart afterwards -- both end with the version table reading head.
    """
    return "upgrade" if has_alembic_version else "stamp"


def configured(config: Config) -> Config:
    """
    Point Alembic at the database this process actually uses.

    alembic.ini carries a developer's localhost URL. Inside a container
    that is not the database, it is the container's own loopback, and the
    first version of this connected there and hung.
    """
    url = os.getenv("SYNC_DATABASE_URL")

    if url:
        config.set_main_option("sqlalchemy.url", url)

    return config


def _has_version_table(url: str) -> bool:
    engine = create_engine(url)

    try:
        return inspect(engine).has_table(VERSION_TABLE)
    finally:
        engine.dispose()


def main() -> None:
    logging.basicConfig(level=logging.INFO)

    config = configured(Config(ALEMBIC_INI))
    url = config.get_main_option("sqlalchemy.url")

    action = plan_migration(has_alembic_version=_has_version_table(url))

    if action == "stamp":
        logger.info(
            "[MIGRATE] No %s table: this schema came from the models, "
            "marking it current rather than replaying the chain over it.",
            VERSION_TABLE,
        )
        command.stamp(config, "head")
    else:
        logger.info("[MIGRATE] Applying any pending revisions.")
        command.upgrade(config, "head")

    logger.info("[MIGRATE] Database is at head.")


if __name__ == "__main__":
    main()

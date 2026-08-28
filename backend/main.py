from contextlib import asynccontextmanager
from fastapi import FastAPI
from sqlalchemy import text

from backend.observability.langsmith_setup import setup_langsmith
from backend.observability.logging import RunTagFilter



from backend.config import settings
from backend.services.postgres_service import engine, Base, enable_pgvector
from backend.services.redis_service import ping_redis
from backend.models import db_models  
from backend.api.sql_routes import router as sql_router
from backend.api.vector_routes import router as vector_router
from backend.api.financial_routes import router as financial_router
from backend.api.evaluation_routes import (
    fail_orphaned_runs,
    router as evaluation_router,
)
from backend.api.admin_llm_routes import router as admin_llm_router

import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(run_tag)s %(message)s"
)

# On the handler, so records from every logger — ours and third-party — carry
# the attribute the format string above requires.
for _handler in logging.getLogger().handlers:
    _handler.addFilter(RunTagFilter())

setup_langsmith()

logger = logging.getLogger(__name__)


# Defines an asynchronous application lifespan with startup and shutdown logic.
# Code before 'yield' runs on startup, and code after 'yield' runs on shutdown.
@asynccontextmanager
async def lifespan(app: FastAPI):
    # ───────────── Startup ─────────────

    # Enable the pgvector extension in PostgreSQL
    await enable_pgvector()

    # Development only: create any tables that don't already exist
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    logger.info("pgvector extension enabled")
    logger.info("Database tables checked/created")

    # Benchmarks run as in-process background tasks, so any run still marked
    # active belongs to a process that is already gone and will never be
    # updated again. Close those out before serving, or the dashboard polls
    # them forever and the duplicate guard 409s every rerun.
    orphaned_runs = await fail_orphaned_runs()

    if orphaned_runs:
        logger.warning(
            "[EVALUATION] Failed %d run(s) orphaned by a previous process: %s",
            len(orphaned_runs),
            ", ".join(str(run_id) for run_id in orphaned_runs),
        )

    # Startup complete — FastAPI begins serving requests
    yield

    # ───────────── Shutdown ─────────────

    # Close all database connections in the SQLAlchemy connection pool
    await engine.dispose()

    logger.info("Application shutting down")

# Which routers each deployment mode is allowed to mount.
#
# "portfolio" is the public, unauthenticated preprod: the UI screen and
# nothing else. Everything omitted here either mutates provider
# configuration, re-indexes the corpus, or launches benchmarks that spend
# real provider credit -- none of which can be exposed without a login.
#
# The absence is the control. Unlinking a route from the UI leaves it
# reachable by anyone who guesses the path.
DEPLOYMENT_MODES = ("portfolio", "full")


def build_app(*, deployment_mode: str | None = None) -> FastAPI:
    """
    Assemble the application for one deployment mode.

    Split out of module scope so the mounted surface is testable: the whole
    point of the mode is which routes do not exist, and that cannot be
    asserted against an app that was built at import time.
    """
    mode = deployment_mode or settings.DEPLOYMENT_MODE

    if mode not in DEPLOYMENT_MODES:
        # Loudly, rather than falling through to the permissive branch: a
        # misspelled "portfolio" is exactly how a public deployment ends up
        # serving the admin router.
        raise ValueError(
            f"Unknown DEPLOYMENT_MODE {mode!r}; "
            f"expected one of {DEPLOYMENT_MODES}."
        )

    application = FastAPI(
        title="Financial Intelligence Pipeline",
        lifespan=lifespan,
    )

    # The UI screen's own endpoint, in every mode.
    application.include_router(financial_router)

    if mode == "full":
        application.include_router(admin_llm_router)
        application.include_router(sql_router)
        application.include_router(vector_router)
        application.include_router(evaluation_router)

    _register_health(application)

    return application


def _register_health(application: FastAPI) -> None:
    @application.get("/health")
    async def health():
        db_status = "connected"
        redis_status = "connected"

        try:
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
        except Exception:
            # The exception text carries the connection target, and this
            # endpoint is public in portfolio mode. Logged, not returned.
            logger.exception("Health check: database unreachable")
            db_status = "error"

        try:
            ping_redis()
        except Exception:
            logger.exception("Health check: redis unreachable")
            redis_status = "error"

        return {
            "status": "ok",
            "db": db_status,
            "redis": redis_status,
        }


app = build_app()

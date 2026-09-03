from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from backend.observability.langsmith_setup import setup_langsmith
from backend.observability.logging import RunTagFilter



from fastapi import Depends

from backend.auth.dependencies import require_role
from backend.auth.roles import Role
from backend.config import settings
from backend.services.postgres_service import engine, Base, enable_pgvector
from backend.services.redis_service import ping_redis
from backend.models import db_models  
from backend.api.sql_routes import router as sql_router
from backend.api.admin_links_routes import router as admin_links_router
from backend.api.ingestion_routes import router as ingestion_router
from backend.api.vector_routes import router as vector_router
from backend.api.financial_routes import router as financial_router
from backend.api.evaluation_routes import (
    fail_orphaned_runs,
    router as evaluation_router,
)
from backend.api.escalation_routes import router as escalation_router
from backend.api.security_routes import router as security_router
from backend.api.admin_llm_routes import router as admin_llm_router
from backend.api.auth_routes import router as auth_router

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

    # Signing in, in every mode: every other router now needs a token.
    application.include_router(auth_router)

    # The console's endpoint, in every mode -- but guarded only where there
    # is a login to guard it with.
    #
    # Portfolio mode is the public demo: anyone with the link asks a
    # question without signing in, and the rate limiter is the control, as
    # financial_routes has always said ("preprod has no authentication, so
    # the ceiling is about cost rather than login abuse"). Full mode sits
    # behind a login, so the same route requires the analyst role.
    #
    # Attached at mount rather than on the route, so the mode is the single
    # place this is decided and the route table can be asserted against.
    application.include_router(
        financial_router,
        dependencies=(
            []
            if mode == "portfolio"
            else [Depends(require_role(Role.ANALYST))]
        ),
    )

    if mode == "full":
        application.include_router(admin_llm_router)
        application.include_router(sql_router)
        application.include_router(vector_router)
        application.include_router(ingestion_router)
        application.include_router(admin_links_router)
        application.include_router(evaluation_router)
        application.include_router(escalation_router)
        application.include_router(security_router)

    _register_health(application, mode)

    # Last, so every route above wins the match. The dashboard's
    # fallback is a catch-all; registered earlier it would swallow the
    # API and answer /health with HTML.
    _serve_frontend(application)

    return application


def _frontend_dist() -> Path:
    """Where `npm run build` leaves the dashboard."""
    return Path(__file__).resolve().parent.parent / "frontend" / "dist"


def _serve_frontend(application: FastAPI) -> None:
    """
    Serve the built dashboard from this app.

    Locally Vite serves the UI and proxies /api here, so nothing ever
    needed to. In the container there is no Vite, and the deployed stack
    answered 404 at its own front door while the built assets sat unused
    inside the image.

    The frontend calls the API with relative paths, so serving both from
    one origin needs no rebuild and raises no CORS question.
    """
    dist = _frontend_dist()
    index = dist / "index.html"

    if not index.is_file():
        # A checkout that has never run `npm run build`. The API is still
        # perfectly usable; refusing to start over a missing UI is not.
        logger.info("No frontend build at %s; serving the API only", dist)

        return

    assets = dist / "assets"

    if assets.is_dir():
        application.mount(
            "/assets", StaticFiles(directory=assets), name="assets"
        )

    @application.get("/{spa_path:path}", include_in_schema=False)
    async def dashboard(spa_path: str):
        # React Router owns paths this server has never heard of, so an
        # unknown path is a screen and gets index.html. An unknown /api
        # path is a missing endpoint, and must still look missing --
        # answering it with HTML turns a typo into a silent success.
        if spa_path.startswith(("api/", "admin/")):
            raise HTTPException(status_code=404)

        asset = dist / spa_path

        if spa_path and asset.is_file():
            return FileResponse(asset)

        return FileResponse(index)


def _register_health(application: FastAPI, mode: str) -> None:
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
            # The frontend cannot tell which deployment it is talking to.
            # Without this it shows a sign-in page on the public demo,
            # where there are no accounts to sign in with.
            "auth_required": mode != "portfolio",
        }


app = build_app()

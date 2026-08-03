from contextlib import asynccontextmanager
from fastapi import FastAPI
from sqlalchemy import text
from backend.services.postgres_service import engine, Base, enable_pgvector
from backend.services.redis_service import ping_redis
from backend.models import db_models  
from backend.api.sql_routes import router as sql_router
from backend.api.vector_routes import router as vector_router
from backend.api.financial_routes import router as financial_router
from backend.api.evaluation_routes import router as evaluation_router
from backend.api.admin_llm_routes import router as admin_llm_router

import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(message)s"
)

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

    # Startup complete — FastAPI begins serving requests
    yield

    # ───────────── Shutdown ─────────────

    # Close all database connections in the SQLAlchemy connection pool
    await engine.dispose()

    logger.info("Application shutting down")

app = FastAPI(title="Financial Intelligence Pipeline", lifespan=lifespan)

app.include_router(admin_llm_router)
app.include_router(sql_router)
app.include_router(vector_router)
app.include_router(financial_router)
app.include_router(evaluation_router)


@app.get("/health")
async def health():
    db_status = "connected"
    redis_status = "connected"

    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception as e:
        db_status = f"error: {str(e)}"

    try:
        ping_redis()
    except Exception as e:
        redis_status = f"error: {str(e)}"

    return {
        "status": "ok",
        "db": db_status,
        "redis": redis_status
    }
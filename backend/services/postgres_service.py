from collections.abc import AsyncGenerator

from sqlalchemy import text
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from backend.config import settings
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

class Base(DeclarativeBase):
    pass

engine = create_async_engine(
    settings.DATABASE_URL,   # PostgreSQL connection URL
    pool_pre_ping=True,      # Verify connection is alive before using it
    pool_size=10,            # Keep up to 10 persistent connections in the pool
    max_overflow=20,         # Allow up to 20 additional temporary connections during traffic spikes
    pool_timeout=30,         # Wait up to 30 seconds for a free connection before raising an error
    pool_recycle=1800,       # Recreate connections every 30 minutes to avoid stale/idle connections
    echo=False,              # Don't log SQL statements (set True for debugging)
)

# Create a factory for asynchronous database sessions
AsyncSessionLocal = async_sessionmaker(
    bind=engine,                 # Use the configured async database engine
    class_=AsyncSession,         # Create AsyncSession objects
    expire_on_commit=False,      # Keep objects accessible after commit (don't reload automatically)
    autoflush=False,             # Only flush changes when commit() or flush() is explicitly called
)

async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise

async def enable_pgvector():
    async with engine.begin() as connection:
        await connection.execute(
            text("CREATE EXTENSION IF NOT EXISTS vector")
        )
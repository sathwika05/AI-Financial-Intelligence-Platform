"""
Shared pytest setup.

Loads .env before any test module is imported.

The container gets these through compose's `env_file:`, but a bare
`uv run pytest` on the host does not, and several modules read
configuration at import time rather than on first use —
backend.ingestion.indexing_service constructs OpenAIEmbeddings at module
scope, and backend.retrieval.sql_executor opens a database connection to
build SCHEMA. Collection therefore failed on the host with "Missing
credentials" before a single test ran.

override=False so a variable already exported in the shell wins, which is
what makes it possible to point a run at a different database without
editing the file.
"""
from pathlib import Path

from dotenv import load_dotenv


load_dotenv(
    dotenv_path=Path(__file__).resolve().parents[1] / ".env",
    override=False,
)

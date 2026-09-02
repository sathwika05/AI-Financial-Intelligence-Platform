"""add hnsw index on document chunk embeddings

Revision ID: ed2de6d3b0f7
Revises: b4e81f6c03da
Create Date: 2026-09-01

Vector search ordered by `embedding <=> query` with no index on the column,
so every question scanned all of document_chunks. At 327 rows that is
milliseconds and Postgres will likely keep choosing a sequential scan --
this index earns nothing today and is here for the corpus that does not
fit one.

Measured after creating it, on 327 rows:

    Seq Scan on document_chunks (rows=327)   -- index not used
    Execution Time: 2.674 ms

So retrieval is unchanged, and so are the benchmark scores. The planner
will start choosing it somewhere in the tens of thousands of rows, and
that is the point at which the approximation below starts to matter.

vector_cosine_ops, because the query uses <=>. An index built for a
different operator is simply never used, silently, which is the failure
mode worth naming: nothing errors, the scan just stays sequential.

HNSW rather than IVFFlat: IVFFlat wants training data to build its lists
and degrades when the corpus grows past what it was built against, so it
needs rebuilding as documents arrive. HNSW does not.

The trade is recall. HNSW is approximate, so retrieval can return a
different set than an exact scan would -- which is a real consideration
for a benchmark that grades retrieval. ef_search stays at its default
here; raising it recovers recall at the cost of latency, and neither is
worth tuning against 327 rows.

Built without CONCURRENTLY. On this table it takes milliseconds, and
CONCURRENTLY cannot run inside the transaction a migration is wrapped in.
On a corpus large enough for this index to matter, that decision should
be revisited -- a plain CREATE INDEX takes an exclusive lock.
"""
from typing import Sequence, Union

from alembic import op


revision: str = "ed2de6d3b0f7"
down_revision: Union[str, None] = "b4e81f6c03da"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


INDEX = "ix_document_chunks_embedding_hnsw"


def upgrade() -> None:
    op.execute(
        f"""
        CREATE INDEX IF NOT EXISTS {INDEX}
        ON document_chunks
        USING hnsw (embedding vector_cosine_ops)
        """
    )


def downgrade() -> None:
    op.execute(f"DROP INDEX IF EXISTS {INDEX}")

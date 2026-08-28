"""add retrieval flags to benchmark_runs

Records which retrieval pipeline produced a run, so baseline, RRF only,
cross-encoder only and both can be told apart after the fact.

Both default to false rather than null. A run recorded before these columns
existed is not of unknown configuration — it is known to have used the
baseline pipeline, because that was the only one there was.

Revision ID: a1c7f3e29d84
Revises: f4a1c8e93b27
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "a1c7f3e29d84"
down_revision: Union[str, Sequence[str], None] = "f4a1c8e93b27"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ADD COLUMN needs ACCESS EXCLUSIVE, which conflicts with the ACCESS
    # SHARE a plain SELECT holds. A connection left idle in transaction
    # therefore blocks this indefinitely — and once this statement is
    # queued waiting, every later query on benchmark_runs queues behind
    # it, which turns a fast migration into an outage on a live run.
    #
    # Fail instead of waiting. Both columns are metadata-only additions on
    # PostgreSQL 11+, so when the lock is free this takes microseconds.
    op.execute("SET lock_timeout = '3s'")

    op.add_column(
        "benchmark_runs",
        sa.Column(
            "rrf_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "benchmark_runs",
        sa.Column(
            "cross_encoder_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.drop_column("benchmark_runs", "cross_encoder_enabled")
    op.drop_column("benchmark_runs", "rrf_enabled")

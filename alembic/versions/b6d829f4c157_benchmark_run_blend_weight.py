"""add llm_blend_weight to benchmark_runs

The weight became configurable per run, and nothing recorded which value
a run used -- so four ablation arms would appear identically in the runs
list with no way to tell them apart. That defeats the point of running
them.

Nullable rather than defaulting to 0.3, and the distinction matters here
in a way it did not for rrf_enabled. Both flags off is what every earlier
run genuinely was, so a false server_default records a known fact. A
blend weight is different: rows written before the weight was
configurable used whatever the ranker's default was at the time, which is
not the same claim as "this run chose 0.3". NULL says "did not choose",
and the UI renders it as Default so a reader sees the behaviour without
the row asserting an intent it never had.

That also keeps the two readings apart if the ranker's default ever
moves: old rows follow the new default, rows that chose 0.3 keep 0.3.

Revision ID: b6d829f4c157
Revises: a8c47e0b93d5
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b6d829f4c157"
down_revision: Union[str, Sequence[str], None] = "a8c47e0b93d5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "benchmark_runs",
        sa.Column("llm_blend_weight", sa.Float(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("benchmark_runs", "llm_blend_weight")

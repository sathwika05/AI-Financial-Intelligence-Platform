"""add node_latency to evaluation_metrics

Revision ID: f73d92e4b118
Revises: e58b3d71ca44
Create Date: 2026-08-16

Adds the per-node latency breakdown behind the dashboard's "Latency by Node"
panel. The graph now times each node via the wrapper in financial_graph, and
the runner carries those timings onto every question result.

Nullable: runs recorded before the graph was instrumented have no per-node
timings to backfill.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'f73d92e4b118'
down_revision: Union[str, Sequence[str], None] = 'e58b3d71ca44'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "evaluation_metrics",
        sa.Column(
            "node_latency",
            sa.JSON(),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column(
        "evaluation_metrics",
        "node_latency",
    )

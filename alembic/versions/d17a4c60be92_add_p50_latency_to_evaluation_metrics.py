"""add p50_latency to evaluation_metrics

Revision ID: d17a4c60be92
Revises: c92e5b81f307
Create Date: 2026-08-16

The run aggregate has always computed p50 alongside p95 and p99, but only the
latter two had columns, so the median was discarded. The latency distribution
chart needs all three.

A separate revision rather than an edit to c92e5b81f307, so this applies
cleanly whether or not the earlier revisions have already been run.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'd17a4c60be92'
down_revision: Union[str, Sequence[str], None] = 'c92e5b81f307'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "evaluation_metrics",
        sa.Column(
            "p50_latency",
            sa.Float(),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column(
        "evaluation_metrics",
        "p50_latency",
    )

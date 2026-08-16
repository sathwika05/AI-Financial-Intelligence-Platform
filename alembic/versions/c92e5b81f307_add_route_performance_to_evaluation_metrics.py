"""add route_performance to evaluation_metrics

Revision ID: c92e5b81f307
Revises: b41c7f2ad905
Create Date: 2026-08-16

Adds the per-route metric averages behind the dashboard's SQL / Vector /
Hybrid route performance cards. Kept as a separate revision from
route_distribution so this applies cleanly whether or not that one has
already been run.

Nullable for the same reason: runs recorded before this existed never had
their per-question routes persisted, so there is nothing to backfill.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'c92e5b81f307'
down_revision: Union[str, Sequence[str], None] = 'b41c7f2ad905'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "evaluation_metrics",
        sa.Column(
            "route_performance",
            sa.JSON(),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column(
        "evaluation_metrics",
        "route_performance",
    )

"""add route_distribution to evaluation_metrics

Revision ID: b41c7f2ad905
Revises: 868a3cd08c41
Create Date: 2026-08-16

Adds the per-run count of questions by actual execution route, which the
dashboard's route distribution panel reads. Nullable, because every run
recorded before this migration has no distribution to backfill — the
per-question routes those runs took were never persisted.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'b41c7f2ad905'
down_revision: Union[str, Sequence[str], None] = '868a3cd08c41'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "evaluation_metrics",
        sa.Column(
            "route_distribution",
            sa.JSON(),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column(
        "evaluation_metrics",
        "route_distribution",
    )

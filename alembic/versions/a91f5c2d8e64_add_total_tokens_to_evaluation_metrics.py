"""add total_tokens to evaluation_metrics

Revision ID: a91f5c2d8e64
Revises: f73d92e4b118
Create Date: 2026-08-16

Adds measured LLM token usage per run. The pipeline now attaches a usage
tracker to the invocation config, so every call's reported token counts are
accumulated and priced against the provider's configured per-model rates.

This also fixes total_cost, which previously read a `total_cost_usd` state
key that no node ever wrote — every run therefore recorded a cost of zero.

Nullable: runs recorded before the tracker existed have no usage to backfill.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'a91f5c2d8e64'
down_revision: Union[str, Sequence[str], None] = 'f73d92e4b118'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "evaluation_metrics",
        sa.Column("total_tokens", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("evaluation_metrics", "total_tokens")

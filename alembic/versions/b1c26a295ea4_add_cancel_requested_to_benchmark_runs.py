"""add cancel_requested to benchmark_runs

Revision ID: b1c26a295ea4
Revises: a1c7f3e29d84
Create Date: 2026-08-28 15:47:40.883702

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b1c26a295ea4'
down_revision: Union[str, Sequence[str], None] = 'a1c7f3e29d84'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add the flag the cancel endpoint raises.

    NOT NULL with a server-side default, so the 100-plus rows written
    before this column existed read as "not cancelled" rather than NULL —
    the runner treats the flag as a plain boolean.
    """
    op.add_column(
        "benchmark_runs",
        sa.Column(
            "cancel_requested",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.drop_column("benchmark_runs", "cancel_requested")

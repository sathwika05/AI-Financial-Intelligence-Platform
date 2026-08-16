"""add tool_summary to evaluation_metrics

Revision ID: e58b3d71ca44
Revises: d17a4c60be92
Create Date: 2026-08-16

Adds per-tool invocation counts behind the dashboard's tool execution
summary. Derived from the executed tools each question recorded and the
tools its golden entry expected, both of which the runner already had in
memory and discarded.

A separate revision so it applies cleanly whether or not the earlier ones
have already been run.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'e58b3d71ca44'
down_revision: Union[str, Sequence[str], None] = 'd17a4c60be92'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "evaluation_metrics",
        sa.Column(
            "tool_summary",
            sa.JSON(),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column(
        "evaluation_metrics",
        "tool_summary",
    )

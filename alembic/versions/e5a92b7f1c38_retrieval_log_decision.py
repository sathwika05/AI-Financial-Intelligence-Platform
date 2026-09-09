"""add decision to retrieval_logs

retrieval_logs holds query, retrieval_path, latency_ms and created_at,
which answers "how many, how fast, by which route" and nothing about how
the query ended.

Two of the numbers an operations view is expected to show -- the withheld
percentage and the escalation count -- cannot be derived from those four
columns. Neither can the more useful version of the latency question:
"p95 of the queries we actually answered", as distinct from p95 including
the ones that were refused in a second because they were out of scope.
Those two populations have nothing to do with each other and averaging
them together describes neither.

So `decision` is added now rather than in a second migration once the
view is being built: approved, forced_pass, withheld_empty_draft,
withheld_review_unavailable, withheld_provider_unavailable, or
OUT_OF_SCOPE.

Nullable, because a request that fails before the reviewer runs has no
decision, and a default would invent one. Indexed with created_at,
because every operational query filters on a time window and groups by
outcome.

Revision ID: e5a92b7f1c38
Revises: d3f81c26a5e4
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e5a92b7f1c38"
down_revision: Union[str, Sequence[str], None] = "d3f81c26a5e4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "retrieval_logs",
        sa.Column("decision", sa.String(), nullable=True),
    )
    op.create_index(
        "ix_retrieval_logs_created_decision",
        "retrieval_logs",
        ["created_at", "decision"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_retrieval_logs_created_decision",
        table_name="retrieval_logs",
    )
    op.drop_column("retrieval_logs", "decision")

"""add ingestion events

Revision ID: f7c2a940e15b
Revises: e2d4b6a91c37
Create Date: 2026-08-30

One row per attempt to bring a file into the corpus, however it ended.

Everything else visible about ingestion is an outcome: a documents row, a
status, a chunk count. A file that produced no row produced no trace
either — a duplicate, an unreadable PDF, a filing whose text could not be
read, a collection run that fetched nothing. Those are precisely the
cases someone needs to see, and they are the ones that disappear.

The columns are shaped by that. `outcome` is a closed set rather than
free text, so failures can be counted rather than described six different
ways; `detail` carries the reason, which is the only thing that makes a
failed row actionable; `document_id` and `chunks` are null unless
something was actually stored, so a glance down the table separates the
attempts that grew the corpus from the ones that did not.

`source` records the route — upload, sec_edgar, s3 — not the publisher.
Documents deliberately cannot say which route brought them in, because
both write the same provenance so the duplicate check treats them as one
document. This is where that distinction lives instead.

Nothing reads this in retrieval.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "f7c2a940e15b"
down_revision: Union[str, Sequence[str], None] = "e2d4b6a91c37"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ingestion_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("reference", sa.String(), nullable=False),
        sa.Column("outcome", sa.String(length=16), nullable=False),
        sa.Column("detail", sa.Text(), nullable=True),
        # Nullable, and no cascade: an event describes what happened, and
        # deleting the document does not unmake the attempt.
        sa.Column("document_id", sa.Integer(), nullable=True),
        sa.Column("chunks", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index("ix_ingestion_events_id", "ingestion_events", ["id"])
    op.create_index("ix_ingestion_events_source", "ingestion_events", ["source"])
    op.create_index("ix_ingestion_events_outcome", "ingestion_events", ["outcome"])
    # The table is read newest-first and almost nothing else.
    op.create_index(
        "ix_ingestion_events_created_at", "ingestion_events", ["created_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_ingestion_events_created_at", table_name="ingestion_events")
    op.drop_index("ix_ingestion_events_outcome", table_name="ingestion_events")
    op.drop_index("ix_ingestion_events_source", table_name="ingestion_events")
    op.drop_index("ix_ingestion_events_id", table_name="ingestion_events")
    op.drop_table("ingestion_events")

"""unlink ingestion events from documents

Revision ID: b4e81f6c03da
Revises: f7c2a940e15b
Create Date: 2026-08-30

ingestion_events.document_id carried a foreign key to documents, and
seeds/snapshot.py restores the benchmark corpus with

    TRUNCATE TABLE ... RESTART IDENTITY CASCADE

so restoring emptied the processing log along with it. Running the test
suite did the same, since it exercises restore. The log recording what
happened to each file disappeared whenever the corpus was reset — which
is exactly when someone would want to look at it.

The constraint contradicted what the table is for. An event records that
a file was attempted; that is a fact about the past, and a document being
deleted does not unmake the upload that produced it. The migration that
added the column said as much and then added the key anyway.

The column stays. It is how a row is matched to the document it produced
— recorded rather than enforced, which is the correct relationship for a
log: a row may point at a document that no longer exists, and that is
information rather than corruption.
"""
from typing import Sequence, Union

from alembic import op


revision: str = "b4e81f6c03da"
down_revision: Union[str, Sequence[str], None] = "f7c2a940e15b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Named by Postgres when the table was created.
    op.drop_constraint(
        "ingestion_events_document_id_fkey",
        "ingestion_events",
        type_="foreignkey",
    )


def downgrade() -> None:
    op.create_foreign_key(
        "ingestion_events_document_id_fkey",
        "ingestion_events",
        "documents",
        ["document_id"],
        ["id"],
    )

"""add document status and chunk identity

Revision ID: e2d4b6a91c37
Revises: 0374ccc9ce37
Create Date: 2026-08-29

Three columns, for two jobs neither table could do before.

documents.status
    A document row was written before indexing ran, and nothing recorded
    whether indexing then succeeded. A document whose embedding call
    failed looks exactly like one that worked: a row with no chunks, which
    is also what an empty document looks like. Status makes that state
    nameable, so a failed ingestion can be found and retried instead of
    being discovered by someone asking a question and getting nothing.

    Backfilled to 'ready', because every document already in the table was
    indexed by the seed and is retrievable today.

document_chunks.chunk_uid
    The only identity a chunk had was an autoincrementing primary key,
    which changes on every reindex. That makes "did this document's chunks
    actually change?" unanswerable, and that is precisely the question a
    consistency check between the table and the vectors has to ask. The
    uid is derived from the document, the position and the content, so
    re-indexing unchanged content reproduces it exactly.

    Indexed but not unique. The value here is comparison, not enforcement,
    and a unique constraint that ever fired would turn a reindex into a
    failed message rather than a diff someone can look at.

document_chunks.section
    Docling recovers a filing's headings and the chunker used to throw
    them away, so a passage about margins had nothing to say it came from
    Item 7.

All three are additive and none is read by retrieval, so no query changes
and the benchmark stays comparable. Nullable on the chunk columns because
every row already in the table predates them and there is nothing
truthful to backfill: those chunks were produced by a chunker that did
not record either value.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "e2d4b6a91c37"
down_revision: Union[str, Sequence[str], None] = "0374ccc9ce37"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "documents",
        sa.Column(
            "status",
            sa.String(length=16),
            nullable=False,
            # Existing rows were indexed by the seed and are retrievable
            # today, so 'ready' is the truthful backfill rather than a
            # convenient default.
            server_default="ready",
        ),
    )

    op.create_index(
        "ix_documents_status",
        "documents",
        ["status"],
    )

    op.add_column(
        "document_chunks",
        sa.Column("chunk_uid", sa.String(length=64), nullable=True),
    )

    op.create_index(
        "ix_document_chunks_chunk_uid",
        "document_chunks",
        ["chunk_uid"],
    )

    op.add_column(
        "document_chunks",
        sa.Column("section", sa.String(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("document_chunks", "section")
    op.drop_index("ix_document_chunks_chunk_uid", table_name="document_chunks")
    op.drop_column("document_chunks", "chunk_uid")
    op.drop_index("ix_documents_status", table_name="documents")
    op.drop_column("documents", "status")

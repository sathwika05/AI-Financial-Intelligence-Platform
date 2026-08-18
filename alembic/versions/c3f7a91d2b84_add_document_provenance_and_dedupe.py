"""add document provenance and dedupe identity

Revision ID: c3f7a91d2b84
Revises: a91f5c2d8e64
Create Date: 2026-08-18

News seeding queried Alpha Vantage's NEWS_SENTIMENT per ticker and then
assumed every returned article belonged to that ticker. That endpoint
returns loosely related market news, so one AMD bond-sale article was
stored five times — under AMD, JPM, BAC, MS and C — and only the AMD copy
was correct. Alpha Vantage reports a per-ticker relevance score that would
have rejected the other four; the seed discarded it.

The seed also discarded the article URL and had no duplicate detection, so
the same article fetched under several tickers became several rows.

These columns give a document its provenance and two independent duplicate
identities:

  source_url      canonical URL, tracking parameters removed
  content_hash    SHA-256 of the whitespace-normalised content
  relevance_score how strongly the provider tied the article to its company
  title           kept alongside content, which stores the summary

Nullable throughout: documents seeded before this migration have no URL,
hash or relevance to backfill, and Finnhub's company-news endpoint is
already company-scoped so it reports no relevance score.

The unique constraints are the durable guarantee. The seed checks for
duplicates before inserting, but the constraint is what stops any other
writer reintroducing one. Postgres permits repeated NULLs in a unique
index, so articles without a URL are not forced into conflict with each
other and fall back to content_hash alone.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'c3f7a91d2b84'
down_revision: Union[str, Sequence[str], None] = 'a91f5c2d8e64'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "documents",
        sa.Column("title", sa.String(), nullable=True),
    )
    op.add_column(
        "documents",
        sa.Column("source_url", sa.String(), nullable=True),
    )
    op.add_column(
        "documents",
        sa.Column("content_hash", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "documents",
        sa.Column("relevance_score", sa.Float(), nullable=True),
    )

    op.create_unique_constraint(
        "uq_documents_source_url",
        "documents",
        ["source_url"],
    )
    op.create_unique_constraint(
        "uq_documents_content_hash",
        "documents",
        ["content_hash"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_documents_content_hash",
        "documents",
        type_="unique",
    )
    op.drop_constraint(
        "uq_documents_source_url",
        "documents",
        type_="unique",
    )

    op.drop_column("documents", "relevance_score")
    op.drop_column("documents", "content_hash")
    op.drop_column("documents", "source_url")
    op.drop_column("documents", "title")

"""add themes and company_themes

Revision ID: d5b8c04e71fa
Revises: c3f7a91d2b84
Create Date: 2026-08-18

`companies.sector` held the only categorical fact about a company, and its
eight broad values cannot express "AI", "semiconductor" or "cloud". Asked to
rank AI-related stocks, the SQL generator had nothing to filter on and
manufactured a filter from free text:

    WHERE EXISTS (SELECT 1 FROM documents d
                  WHERE d.company_id = c.id AND d.content ILIKE '%AI%')

That selected 35 of 50 companies — '%AI%' matches the letters "ai" inside
ordinary words, so an oil producer qualified because one of its articles
contained "maintains". An earlier variant, `c.sector ILIKE '%AI%'`, returned
zero rows instead. Forbidding each pattern in the prompt only moved the
problem to the next column; the durable fix is to give the question
something real to filter on.

Many-to-many rather than a column on `companies`: NVDA is both AI and
Semiconductors, and a per-theme boolean column would need a migration for
every new category.

ON DELETE CASCADE on both foreign keys because these rows are derived
membership facts, meaningless once either side is gone — and the seed
truncates `companies` on every run.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'd5b8c04e71fa'
down_revision: Union[str, Sequence[str], None] = 'c3f7a91d2b84'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "themes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("slug", sa.String(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug"),
    )
    op.create_index("ix_themes_id", "themes", ["id"])

    op.create_table(
        "company_themes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("theme_id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["companies.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["theme_id"],
            ["themes.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "company_id",
            "theme_id",
            name="uq_company_themes_company_theme",
        ),
    )
    op.create_index("ix_company_themes_id", "company_themes", ["id"])
    op.create_index(
        "ix_company_themes_theme_id",
        "company_themes",
        ["theme_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_company_themes_theme_id", table_name="company_themes")
    op.drop_index("ix_company_themes_id", table_name="company_themes")
    op.drop_table("company_themes")

    op.drop_index("ix_themes_id", table_name="themes")
    op.drop_table("themes")

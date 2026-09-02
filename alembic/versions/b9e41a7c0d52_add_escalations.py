"""add escalations

The queue behind human-in-the-loop review. A report below the reviewer's
escalation threshold is withheld from the analyst and lands here instead,
carrying the draft the analyst never saw.

Revision ID: b9e41a7c0d52
Revises: ed2de6d3b0f7
Create Date: 2026-09-02

"""
from alembic import op
import sqlalchemy as sa


revision = "b9e41a7c0d52"
down_revision = "ed2de6d3b0f7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "escalations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("intent", sa.String(length=20), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("notice", sa.Text(), nullable=True),
        # The withheld draft and the reviewer's flags. JSON rather than
        # columns: the report's shape is the analysis node's business and
        # has changed twice, and nothing here is queried by field.
        sa.Column("withheld_report", sa.JSON(), nullable=True),
        sa.Column("review_flags", sa.JSON(), nullable=True),
        sa.Column(
            "status",
            sa.String(length=16),
            server_default="pending",
            nullable=False,
        ),
        sa.Column("reviewed_by", sa.String(), nullable=True),
        sa.Column("resolution_note", sa.Text(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index(
        op.f("ix_escalations_id"), "escalations", ["id"], unique=False
    )
    # The admin queue reads one status at a time, newest first.
    op.create_index(
        op.f("ix_escalations_status"), "escalations", ["status"], unique=False
    )
    op.create_index(
        op.f("ix_escalations_created_at"),
        "escalations",
        ["created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_escalations_created_at"), table_name="escalations")
    op.drop_index(op.f("ix_escalations_status"), table_name="escalations")
    op.drop_index(op.f("ix_escalations_id"), table_name="escalations")
    op.drop_table("escalations")

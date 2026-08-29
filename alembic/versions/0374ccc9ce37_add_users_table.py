"""add users table

Revision ID: 0374ccc9ce37
Revises: b1c26a295ea4
Create Date: 2026-08-29 08:04:05.173388

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '0374ccc9ce37'
down_revision: Union[str, Sequence[str], None] = 'b1c26a295ea4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    People who can sign in.

    role is text rather than a database enum: adding a third role later
    should not need a migration on this column. is_active defaults true
    server-side so a row inserted by hand is usable.
    """
    op.create_table(
        "users",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
        ),
        sa.Column("email", sa.String(), nullable=False),
        sa.Column("password_hash", sa.String(), nullable=False),
        sa.Column(
            "role",
            sa.String(),
            nullable=False,
            server_default="analyst",
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
        ),
    )

    # Unique and indexed: the login path looks up by email on every
    # request, and two rows for one address would make it ambiguous.
    op.create_index(
        "ix_users_email",
        "users",
        ["email"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_users_email", table_name="users")
    op.drop_table("users")

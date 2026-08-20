"""add question_results

Revision ID: f4a1c8e93b27
Revises: d5b8c04e71fa
Create Date: 2026-08-20

evaluation_metrics holds one averaged row per benchmark run, so nothing
recorded how an individual question scored. The only trace was a log line
printed during the run, which meant a question could not be compared
across runs, a regression could not be attributed to the question that
caused it, and the dashboard could show a run's average but never its
shape. Recovering even one run's detail meant parsing interleaved
container logs.

evaluator_results and aggregate_metrics are JSON rather than columns.
Which evaluators apply varies by question — ragas and market do not run
for every one, and sql gained order-correctness and top-k-membership
diagnostics recently — so a column per metric would need a migration for
each new one and leave every earlier row null. The averaged, queryable
copy already lives on evaluation_metrics; this table keeps the detail.

The unique constraint on (run_id, question_id) makes persistence
idempotent: a question appears once per run, so re-persisting updates
rather than accumulating duplicates.

Nullable throughout, because a question that raised has no scores to
record and its error message is the result.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID as PG_UUID


# revision identifiers, used by Alembic.
revision: str = 'f4a1c8e93b27'
down_revision: Union[str, Sequence[str], None] = 'd5b8c04e71fa'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "question_results",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("run_id", PG_UUID(as_uuid=True), nullable=True),
        sa.Column("question_id", sa.String(), nullable=False),
        sa.Column("question", sa.Text(), nullable=True),
        sa.Column("expected_intent", sa.String(), nullable=True),
        sa.Column("actual_intent", sa.String(), nullable=True),
        sa.Column("overall_score", sa.Float(), nullable=True),
        sa.Column("passed", sa.Boolean(), nullable=True),
        sa.Column("evaluator_results", sa.JSON(), nullable=True),
        sa.Column("aggregate_metrics", sa.JSON(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["benchmark_runs.run_id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "run_id",
            "question_id",
            name="uq_question_results_run_question",
        ),
    )
    op.create_index("ix_question_results_id", "question_results", ["id"])
    op.create_index(
        "ix_question_results_run_id",
        "question_results",
        ["run_id"],
    )
    # Comparing one question across runs is the read this table exists
    # for, and it filters on question_id alone.
    op.create_index(
        "ix_question_results_question_id",
        "question_results",
        ["question_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_question_results_question_id",
        table_name="question_results",
    )
    op.drop_index(
        "ix_question_results_run_id",
        table_name="question_results",
    )
    op.drop_index("ix_question_results_id", table_name="question_results")
    op.drop_table("question_results")

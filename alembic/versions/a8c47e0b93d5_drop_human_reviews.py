"""drop human_reviews

Never had a writer, and the loop it described exists elsewhere and works.

WHERE HUMAN REVIEW ACTUALLY LIVES

    escalations. record_escalation files a row whenever the reviewer
    withholds a report, GET /api/escalations serves the queue, and
    POST /api/escalations/{id}/resolve records what the administrator
    decided -- with the reviewer taken from the token rather than a body
    field, so it cannot be typed in as somebody else. HumanReviewScreen
    reads it. The table already carries status, reviewed_by,
    resolution_note and reviewed_at.

WHAT THIS TABLE WAS INSTEAD

    Keyed on run_id -> benchmark_runs, holding question, answer, rating
    and reviewer_notes: a human scoring a benchmark answer. That is a
    different loop, for grading evaluation output rather than for
    deciding whether a withheld production answer should have been
    withheld -- and it is one we decided not to build. Authored ground
    truth is written before a run, not rated after it.

    So this is schema describing a second review loop that does not exist
    beside a first one that does. Keeping it invites the reasonable
    conclusion that human review is unfinished, when the part that
    matters is finished.

Third table deleted rather than filled, after alerts and pipeline_traces.
The distinction each time was whether anything could answer a question
with it that nothing else could: retrieval_logs, model_costs and
retrieved_evidence could, and got writers.

Not to be confused with the escalation rows written in portfolio mode,
which are deliberate: escalation_router is not mounted there, so nothing
reads them back over HTTP, but the rows are the record of what the public
demo declined to stand behind and are read out of band. Rows nobody
serves are not the same as a table nobody writes.

Hand-written for the reason 7fda2e226bca gives. Round-tripped against a
real database.

Revision ID: a8c47e0b93d5
Revises: f7b3c19d4a62
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "a8c47e0b93d5"
down_revision: Union[str, Sequence[str], None] = "f7b3c19d4a62"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_index("ix_human_reviews_id", table_name="human_reviews")
    op.drop_table("human_reviews")


def downgrade() -> None:
    op.create_table(
        "human_reviews",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("question", sa.Text(), nullable=True),
        sa.Column("answer", sa.Text(), nullable=True),
        sa.Column("rating", sa.Integer(), nullable=True),
        sa.Column("reviewer_notes", sa.Text(), nullable=True),
        sa.Column(
            "reviewed_at",
            sa.DateTime(),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(["run_id"], ["benchmark_runs.run_id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_human_reviews_id", "human_reviews", ["id"], unique=False
    )

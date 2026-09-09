"""add question_id to retrieved_evidence

The table has a run_id and nothing finer, so evidence could only ever be
attributed to a whole benchmark run. That is the wrong grain for the
thing it exists to answer.

WHY THE GRAIN MATTERS

    The point of keeping retrieved evidence is to make an ablation
    explainable. Comparing an RRF arm against a dense-only arm gives a
    number -- ndcg 0.71 to 0.73 -- and if that delta sits inside the 0.04
    judge noise floor it means nothing on its own. What makes it mean
    something is being able to ask "which chunk did hybrid surface that
    dense retrieval ranked fourteenth", and that question is per
    question, not per run.

    Without question_id the two arms' evidence is two undifferentiated
    piles of a few hundred rows each, and no diff between them is
    interpretable.

question_id is a string, matching question_results.question_id, so the
two join. Indexed with run_id because every query filters on both.

Nullable, because rows written before this column existed have no
question to attribute -- there are none today, but a nullable column
says "unknown" where a default would invent an answer.

Revision ID: d3f81c26a5e4
Revises: c1d4a8e37b90
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d3f81c26a5e4"
down_revision: Union[str, Sequence[str], None] = "c1d4a8e37b90"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "retrieved_evidence",
        sa.Column("question_id", sa.String(), nullable=True),
    )
    op.create_index(
        "ix_retrieved_evidence_run_question",
        "retrieved_evidence",
        ["run_id", "question_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_retrieved_evidence_run_question",
        table_name="retrieved_evidence",
    )
    op.drop_column("retrieved_evidence", "question_id")

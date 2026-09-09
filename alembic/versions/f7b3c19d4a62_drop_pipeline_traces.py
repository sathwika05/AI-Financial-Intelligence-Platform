"""drop pipeline_traces

The table has never had a writer, and by the time one was being written
it turned out three things already covered it.

    LangSmith has the trace hierarchy. LangGraph opens one run per
    registered node, named after the string passed to add_node, and the
    retrieval branches carry @traceable -- 57 instrumented spans in all.
    backend/observability/tracing.py says so in its own module docstring,
    and deliberately does not add a second span per node for exactly this
    reason.

    node_timings carries per-node latency in state, which
    aggregation.build_node_latency turns into the dashboard's per-node
    panel, with p50/p95/p99 alongside the mean.

    model_costs now carries node_name, tokens_in, tokens_out and
    cost_usd. Those are four of this table's columns, and the remaining
    ones -- started_at, ended_at, status, error_msg -- are the trace
    detail LangSmith is better at than a row ever will be.

So this would be a third copy of data two systems already hold, kept in
the one place nothing reads. The four tables that stay each earn it by
answering something neither of the others can: retrieval_logs and
model_costs join to decisions and runs in SQL, and retrieved_evidence
supports a chunk-level diff between ablation arms.

The line worth writing down is where the boundary falls: per-node tracing
is LangSmith's job, and the database keeps what has to be joined or
aggregated.

Hand-written for the reason 7fda2e226bca gives. The downgrade recreates
the table as it stands today -- UUID run_id, per 35b815b0f476 -- though
if per-node persistence is ever wanted again it should be designed for
whatever needs it, not restored from here.

Revision ID: f7b3c19d4a62
Revises: e5a92b7f1c38
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "f7b3c19d4a62"
down_revision: Union[str, Sequence[str], None] = "e5a92b7f1c38"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_index("ix_pipeline_traces_run_id", table_name="pipeline_traces")
    op.drop_index("ix_pipeline_traces_id", table_name="pipeline_traces")
    op.drop_table("pipeline_traces")


def downgrade() -> None:
    op.create_table(
        "pipeline_traces",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("node_name", sa.String(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("ended_at", sa.DateTime(), nullable=True),
        sa.Column("latency_ms", sa.Float(), nullable=True),
        sa.Column("tokens_in", sa.Integer(), nullable=True),
        sa.Column("tokens_out", sa.Integer(), nullable=True),
        sa.Column("cost_usd", sa.Float(), nullable=True),
        sa.Column("retry_count", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(), nullable=True),
        sa.Column("error_msg", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(["run_id"], ["benchmark_runs.run_id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_pipeline_traces_id", "pipeline_traces", ["id"], unique=False
    )
    op.create_index(
        "ix_pipeline_traces_run_id",
        "pipeline_traces",
        ["run_id"],
        unique=False,
    )

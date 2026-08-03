"""convert run ids to uuid

Revision ID: 35b815b0f476
Revises: d915f0965263
Create Date: 2026-07-15 16:49:05.821487

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '35b815b0f476'
down_revision: Union[str, Sequence[str], None] = 'd915f0965263'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Drop foreign keys before changing column types
    op.drop_constraint(
        "alerts_run_id_fkey",
        "alerts",
        type_="foreignkey",
    )
    op.drop_constraint(
        "human_reviews_run_id_fkey",
        "human_reviews",
        type_="foreignkey",
    )
    op.drop_constraint(
        "model_costs_run_id_fkey",
        "model_costs",
        type_="foreignkey",
    )
    op.drop_constraint(
        "pipeline_traces_run_id_fkey",
        "pipeline_traces",
        type_="foreignkey",
    )
    op.drop_constraint(
        "retrieved_evidence_run_id_fkey",
        "retrieved_evidence",
        type_="foreignkey",
    )
    op.drop_constraint(
        "system_logs_run_id_fkey",
        "system_logs",
        type_="foreignkey",
    )

    # 2. Convert parent column first
    op.alter_column(
        "benchmark_runs",
        "run_id",
        existing_type=sa.VARCHAR(),
        type_=sa.UUID(),
        existing_nullable=False,
        postgresql_using="run_id::uuid",
    )

    # 3. Convert child columns
    op.alter_column(
        "alerts",
        "run_id",
        existing_type=sa.VARCHAR(),
        type_=sa.UUID(),
        existing_nullable=True,
        postgresql_using="run_id::uuid",
    )

    op.alter_column(
        "evaluation_metrics",
        "run_id",
        existing_type=sa.VARCHAR(),
        type_=sa.UUID(),
        existing_nullable=True,
        postgresql_using="run_id::uuid",
    )

    op.alter_column(
        "human_reviews",
        "run_id",
        existing_type=sa.VARCHAR(),
        type_=sa.UUID(),
        existing_nullable=True,
        postgresql_using="run_id::uuid",
    )

    op.alter_column(
        "model_costs",
        "run_id",
        existing_type=sa.VARCHAR(),
        type_=sa.UUID(),
        existing_nullable=True,
        postgresql_using="run_id::uuid",
    )

    op.alter_column(
        "pipeline_traces",
        "run_id",
        existing_type=sa.VARCHAR(),
        type_=sa.UUID(),
        existing_nullable=True,
        postgresql_using="run_id::uuid",
    )

    op.alter_column(
        "retrieved_evidence",
        "run_id",
        existing_type=sa.VARCHAR(),
        type_=sa.UUID(),
        existing_nullable=True,
        postgresql_using="run_id::uuid",
    )

    op.alter_column(
        "system_logs",
        "run_id",
        existing_type=sa.VARCHAR(),
        type_=sa.UUID(),
        existing_nullable=True,
        postgresql_using="run_id::uuid",
    )

    # 4. Recreate foreign keys
    op.create_foreign_key(
        "alerts_run_id_fkey",
        "alerts",
        "benchmark_runs",
        ["run_id"],
        ["run_id"],
    )
    op.create_foreign_key(
        "human_reviews_run_id_fkey",
        "human_reviews",
        "benchmark_runs",
        ["run_id"],
        ["run_id"],
    )
    op.create_foreign_key(
        "model_costs_run_id_fkey",
        "model_costs",
        "benchmark_runs",
        ["run_id"],
        ["run_id"],
    )
    op.create_foreign_key(
        "pipeline_traces_run_id_fkey",
        "pipeline_traces",
        "benchmark_runs",
        ["run_id"],
        ["run_id"],
    )
    op.create_foreign_key(
        "retrieved_evidence_run_id_fkey",
        "retrieved_evidence",
        "benchmark_runs",
        ["run_id"],
        ["run_id"],
    )
    op.create_foreign_key(
        "system_logs_run_id_fkey",
        "system_logs",
        "benchmark_runs",
        ["run_id"],
        ["run_id"],
    )


def downgrade() -> None:
    # Drop UUID foreign keys
    op.drop_constraint("alerts_run_id_fkey", "alerts", type_="foreignkey")
    op.drop_constraint("human_reviews_run_id_fkey", "human_reviews", type_="foreignkey")
    op.drop_constraint("model_costs_run_id_fkey", "model_costs", type_="foreignkey")
    op.drop_constraint("pipeline_traces_run_id_fkey", "pipeline_traces", type_="foreignkey")
    op.drop_constraint("retrieved_evidence_run_id_fkey", "retrieved_evidence", type_="foreignkey")
    op.drop_constraint("system_logs_run_id_fkey", "system_logs", type_="foreignkey")

    # Convert children back to VARCHAR
    for table_name in [
        "alerts",
        "evaluation_metrics",
        "human_reviews",
        "model_costs",
        "pipeline_traces",
        "retrieved_evidence",
        "system_logs",
    ]:
        op.alter_column(
            table_name,
            "run_id",
            existing_type=sa.UUID(),
            type_=sa.VARCHAR(),
            existing_nullable=True,
            postgresql_using="run_id::text",
        )

    # Convert parent back to VARCHAR
    op.alter_column(
        "benchmark_runs",
        "run_id",
        existing_type=sa.UUID(),
        type_=sa.VARCHAR(),
        existing_nullable=False,
        postgresql_using="run_id::text",
    )

    # Recreate VARCHAR foreign keys
    op.create_foreign_key(
        "alerts_run_id_fkey",
        "alerts",
        "benchmark_runs",
        ["run_id"],
        ["run_id"],
    )
    op.create_foreign_key(
        "human_reviews_run_id_fkey",
        "human_reviews",
        "benchmark_runs",
        ["run_id"],
        ["run_id"],
    )
    op.create_foreign_key(
        "model_costs_run_id_fkey",
        "model_costs",
        "benchmark_runs",
        ["run_id"],
        ["run_id"],
    )
    op.create_foreign_key(
        "pipeline_traces_run_id_fkey",
        "pipeline_traces",
        "benchmark_runs",
        ["run_id"],
        ["run_id"],
    )
    op.create_foreign_key(
        "retrieved_evidence_run_id_fkey",
        "retrieved_evidence",
        "benchmark_runs",
        ["run_id"],
        ["run_id"],
    )
    op.create_foreign_key(
        "system_logs_run_id_fkey",
        "system_logs",
        "benchmark_runs",
        ["run_id"],
        ["run_id"],
    )
    # ### end Alembic commands ###

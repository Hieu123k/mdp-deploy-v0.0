"""create migration registry

Revision ID: 202605300010
Revises: 202605300009
Create Date: 2026-05-30 00:10:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "202605300010"
down_revision: Union[str, None] = "202605300009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "migration_jobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=150), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("source_system", sa.String(length=150), nullable=True),
        sa.Column("source_connection_id", sa.Uuid(), nullable=True),
        sa.Column("source_type", sa.String(length=50), nullable=False),
        sa.Column("migration_tool", sa.String(length=50), nullable=False),
        sa.Column("source_schema", sa.String(length=150), nullable=True),
        sa.Column("source_table", sa.String(length=150), nullable=True),
        sa.Column("target_schema", sa.String(length=150), nullable=False),
        sa.Column("target_table", sa.String(length=150), nullable=False),
        sa.Column("estimated_rows", sa.BigInteger(), nullable=True),
        sa.Column("estimated_size_gb", sa.Float(), nullable=True),
        sa.Column("primary_key_columns", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("load_mode", sa.String(length=50), nullable=False),
        sa.Column("status", sa.String(length=50), server_default="active", nullable=False),
        sa.Column("config", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["source_connection_id"], ["connections.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_index(op.f("ix_migration_jobs_name"), "migration_jobs", ["name"])

    op.create_table(
        "migration_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("migration_job_id", sa.Uuid(), nullable=False),
        sa.Column("run_type", sa.String(length=50), nullable=False),
        sa.Column("trigger_type", sa.String(length=50), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("source_row_count", sa.BigInteger(), nullable=True),
        sa.Column("target_row_count", sa.BigInteger(), nullable=True),
        sa.Column("rows_loaded", sa.BigInteger(), nullable=True),
        sa.Column("duration_seconds", sa.Integer(), nullable=True),
        sa.Column("log_text", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("triggered_by", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["migration_job_id"], ["migration_jobs.id"]),
        sa.ForeignKeyConstraint(["triggered_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_migration_runs_migration_job_id"), "migration_runs", ["migration_job_id"])

    op.create_table(
        "migration_validations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("migration_run_id", sa.Uuid(), nullable=False),
        sa.Column("check_name", sa.String(length=150), nullable=False),
        sa.Column("source_value", sa.String(length=255), nullable=True),
        sa.Column("target_value", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["migration_run_id"], ["migration_runs.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_migration_validations_migration_run_id"), "migration_validations", ["migration_run_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_migration_validations_migration_run_id"), table_name="migration_validations")
    op.drop_table("migration_validations")
    op.drop_index(op.f("ix_migration_runs_migration_job_id"), table_name="migration_runs")
    op.drop_table("migration_runs")
    op.drop_index(op.f("ix_migration_jobs_name"), table_name="migration_jobs")
    op.drop_table("migration_jobs")

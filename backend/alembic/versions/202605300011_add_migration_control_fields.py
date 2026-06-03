"""add migration control fields

Revision ID: 202605300011
Revises: 202605300010
Create Date: 2026-05-30 00:11:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "202605300011"
down_revision: Union[str, None] = "202605300010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("migration_jobs", sa.Column("initial_load_strategy", sa.String(length=50), nullable=True))
    op.add_column("migration_jobs", sa.Column("max_rows_per_run", sa.BigInteger(), nullable=True))
    op.add_column("migration_jobs", sa.Column("time_window_column", sa.String(length=150), nullable=True))
    op.add_column("migration_jobs", sa.Column("time_window_column_type", sa.String(length=50), nullable=True))
    op.add_column("migration_jobs", sa.Column("time_window_start", sa.String(length=150), nullable=True))
    op.add_column("migration_jobs", sa.Column("time_window_end", sa.String(length=150), nullable=True))
    op.add_column("migration_jobs", sa.Column("incremental_strategy", sa.String(length=80), nullable=True))
    op.add_column("migration_jobs", sa.Column("watermark_column", sa.String(length=150), nullable=True))
    op.add_column("migration_jobs", sa.Column("watermark_column_type", sa.String(length=50), nullable=True))
    op.add_column("migration_jobs", sa.Column("last_successful_watermark", sa.String(length=150), nullable=True))
    op.add_column("migration_jobs", sa.Column("last_successful_run_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("migration_jobs", sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("migration_jobs", sa.Column("lookback_window_days", sa.Integer(), nullable=True))
    op.add_column("migration_jobs", sa.Column("lookback_window_minutes", sa.Integer(), nullable=True))
    op.add_column(
        "migration_jobs",
        sa.Column("validation_level", sa.String(length=50), server_default="basic", nullable=True),
    )

    op.add_column("migration_runs", sa.Column("run_scope", sa.String(length=255), nullable=True))
    op.add_column("migration_runs", sa.Column("from_watermark", sa.String(length=150), nullable=True))
    op.add_column("migration_runs", sa.Column("to_watermark", sa.String(length=150), nullable=True))
    op.add_column("migration_runs", sa.Column("source_min_watermark", sa.String(length=150), nullable=True))
    op.add_column("migration_runs", sa.Column("source_max_watermark", sa.String(length=150), nullable=True))
    op.add_column("migration_runs", sa.Column("target_min_watermark", sa.String(length=150), nullable=True))
    op.add_column("migration_runs", sa.Column("target_max_watermark", sa.String(length=150), nullable=True))
    op.add_column("migration_runs", sa.Column("validation_status", sa.String(length=50), nullable=True))


def downgrade() -> None:
    op.drop_column("migration_runs", "validation_status")
    op.drop_column("migration_runs", "target_max_watermark")
    op.drop_column("migration_runs", "target_min_watermark")
    op.drop_column("migration_runs", "source_max_watermark")
    op.drop_column("migration_runs", "source_min_watermark")
    op.drop_column("migration_runs", "to_watermark")
    op.drop_column("migration_runs", "from_watermark")
    op.drop_column("migration_runs", "run_scope")

    op.drop_column("migration_jobs", "validation_level")
    op.drop_column("migration_jobs", "lookback_window_minutes")
    op.drop_column("migration_jobs", "lookback_window_days")
    op.drop_column("migration_jobs", "last_run_at")
    op.drop_column("migration_jobs", "last_successful_run_at")
    op.drop_column("migration_jobs", "last_successful_watermark")
    op.drop_column("migration_jobs", "watermark_column_type")
    op.drop_column("migration_jobs", "watermark_column")
    op.drop_column("migration_jobs", "incremental_strategy")
    op.drop_column("migration_jobs", "time_window_end")
    op.drop_column("migration_jobs", "time_window_start")
    op.drop_column("migration_jobs", "time_window_column_type")
    op.drop_column("migration_jobs", "time_window_column")
    op.drop_column("migration_jobs", "max_rows_per_run")
    op.drop_column("migration_jobs", "initial_load_strategy")

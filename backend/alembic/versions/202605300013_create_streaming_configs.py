"""create streaming_configs table (watermark-incremental streaming, per-table config + cursor)

Revision ID: 202605300013
Revises: 202605300012
Create Date: 2026-06-09 12:00:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision: str = "202605300013"
down_revision: Union[str, None] = "202605300012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    jsonb = sa.JSON().with_variant(JSONB, "postgresql")
    op.create_table(
        "streaming_configs",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("source_view", sa.String(length=150), nullable=False),
        sa.Column("target_table", sa.String(length=150), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("ts_col", sa.String(length=150), nullable=True),
        sa.Column("ts_time_col", sa.String(length=150), nullable=True),
        sa.Column("granularity", sa.String(length=20), nullable=False, server_default="day"),
        sa.Column("poll_interval_sec", sa.Integer(), nullable=False, server_default="300"),
        sa.Column("lookback_days", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("primary_key_columns", jsonb, nullable=True),
        sa.Column("last_watermark", sa.String(length=150), nullable=True),
        sa.Column("last_watermark_time", sa.String(length=150), nullable=True),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_rows_added", sa.Integer(), nullable=True),
        sa.Column("last_status", sa.String(length=20), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("config", jsonb, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("source_view", name="uq_streaming_configs_view"),
    )
    op.create_index("ix_streaming_configs_view", "streaming_configs", ["source_view"])


def downgrade() -> None:
    op.drop_index("ix_streaming_configs_view", table_name="streaming_configs")
    op.drop_table("streaming_configs")

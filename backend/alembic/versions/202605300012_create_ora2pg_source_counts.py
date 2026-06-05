"""create ora2pg_source_counts cache table

Revision ID: 202605300012
Revises: 202605300011
Create Date: 2026-06-05 12:00:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "202605300012"
down_revision: Union[str, None] = "202605300011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ora2pg_source_counts",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("source_view", sa.String(length=150), nullable=False),
        sa.Column("target_table", sa.String(length=150), nullable=True),
        sa.Column("source_row_count", sa.BigInteger(), nullable=True),
        sa.Column("count_mode", sa.String(length=20), nullable=True),
        sa.Column("approximate", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="ok"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("counted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("source_view", name="uq_ora2pg_source_counts_view"),
    )
    op.create_index("ix_ora2pg_source_counts_view", "ora2pg_source_counts", ["source_view"])


def downgrade() -> None:
    op.drop_index("ix_ora2pg_source_counts_view", table_name="ora2pg_source_counts")
    op.drop_table("ora2pg_source_counts")

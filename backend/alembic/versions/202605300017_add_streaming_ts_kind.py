"""add streaming_configs.ts_kind (date|sequence) for the 2-case watermark (prompt 35)

Revision ID: 202605300017
Revises: 202605300016
Create Date: 2026-06-10 14:00:00

Additive single column with a safe default ('date' = existing Julian behaviour). down_revision=016
keeps a single alembic head.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "202605300017"
down_revision: Union[str, None] = "202605300016"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "streaming_configs",
        sa.Column("ts_kind", sa.String(length=20), nullable=False, server_default="date"),
    )


def downgrade() -> None:
    op.drop_column("streaming_configs", "ts_kind")

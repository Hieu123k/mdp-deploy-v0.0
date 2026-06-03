"""add generated table to data models

Revision ID: 202605300003
Revises: 202605300002
Create Date: 2026-05-30 00:03:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "202605300003"
down_revision: Union[str, None] = "202605300002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "data_models",
        sa.Column("generated_table", sa.String(length=255), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("data_models", "generated_table")

"""create reference_options table

Revision ID: 202605300012
Revises: 202605300011
Create Date: 2026-06-04 12:00:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "202605300012"
down_revision: Union[str, None] = "202605300011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "reference_options",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("list_key", sa.String(length=80), nullable=False),
        sa.Column("value", sa.String(length=255), nullable=False),
        sa.Column("label", sa.String(length=255), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("extra", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("list_key", "value", name="uq_reference_options_list_value"),
    )
    op.create_index("ix_reference_options_list_key", "reference_options", ["list_key"])


def downgrade() -> None:
    op.drop_index("ix_reference_options_list_key", table_name="reference_options")
    op.drop_table("reference_options")

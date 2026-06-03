"""create data models table

Revision ID: 202605300002
Revises: 202605300001
Create Date: 2026-05-30 00:02:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "202605300002"
down_revision: Union[str, None] = "202605300001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "data_models",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=150), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("type", sa.String(length=1), nullable=False),
        sa.Column("category", sa.String(length=100), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("business_definition", sa.Text(), nullable=True),
        sa.Column("owner_department", sa.String(length=150), nullable=True),
        sa.Column("source_system", sa.String(length=150), nullable=True),
        sa.Column("primary_key", sa.String(length=150), nullable=True),
        sa.Column("attributes", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("relationships", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("refresh_policy", sa.String(length=100), nullable=True),
        sa.Column(
            "sensitivity_level",
            sa.String(length=50),
            server_default="internal",
            nullable=False,
        ),
        sa.Column("ai_enabled", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("status", sa.String(length=50), server_default="active", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_data_models_name"), "data_models", ["name"], unique=True)


def downgrade() -> None:
    op.drop_index(op.f("ix_data_models_name"), table_name="data_models")
    op.drop_table("data_models")

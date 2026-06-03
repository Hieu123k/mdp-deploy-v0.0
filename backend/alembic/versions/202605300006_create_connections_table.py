"""create connections table

Revision ID: 202605300006
Revises: 202605300005
Create Date: 2026-05-30 00:06:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "202605300006"
down_revision: Union[str, None] = "202605300005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "connections",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=150), nullable=False),
        sa.Column("type", sa.String(length=50), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("host", sa.String(length=255), nullable=True),
        sa.Column("port", sa.Integer(), nullable=True),
        sa.Column("database_name", sa.String(length=150), nullable=True),
        sa.Column("username", sa.String(length=150), nullable=True),
        sa.Column("encrypted_password", sa.Text(), nullable=True),
        sa.Column("base_url", sa.String(length=500), nullable=True),
        sa.Column("mqtt_topic_prefix", sa.String(length=255), nullable=True),
        sa.Column("config", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("status", sa.String(length=50), server_default="active", nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("last_test_status", sa.String(length=50), nullable=True),
        sa.Column("last_test_message", sa.Text(), nullable=True),
        sa.Column("last_test_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_index(op.f("ix_connections_name"), "connections", ["name"])
    op.create_index(op.f("ix_connections_type"), "connections", ["type"])


def downgrade() -> None:
    op.drop_index(op.f("ix_connections_type"), table_name="connections")
    op.drop_index(op.f("ix_connections_name"), table_name="connections")
    op.drop_table("connections")

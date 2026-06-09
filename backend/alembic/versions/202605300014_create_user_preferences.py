"""create user_preferences table (Settings: per-user theme + admin tab-config / RBAC visibility)

Revision ID: 202605300014
Revises: 202605300012
Create Date: 2026-06-09 14:00:00

Numbered 014 (down_revision = 012) so it composes cleanly when the streaming feature's 013 is
also present; an integration deployment that has both adds a merge revision unifying the heads.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision: str = "202605300014"
down_revision: Union[str, None] = "202605300012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    jsonb = sa.JSON().with_variant(JSONB, "postgresql")
    op.create_table(
        "user_preferences",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("user_id", sa.Uuid(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("theme", sa.String(length=20), nullable=False, server_default="light"),
        sa.Column("nav_config", jsonb, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("user_id", name="uq_user_preferences_user"),
    )
    op.create_index("ix_user_preferences_user", "user_preferences", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_user_preferences_user", table_name="user_preferences")
    op.drop_table("user_preferences")

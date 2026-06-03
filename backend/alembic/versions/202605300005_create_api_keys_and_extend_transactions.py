"""create api keys and extend transactions

Revision ID: 202605300005
Revises: 202605300004
Create Date: 2026-05-30 00:05:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "202605300005"
down_revision: Union[str, None] = "202605300004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "api_keys",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=150), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("key_prefix", sa.String(length=32), nullable=False),
        sa.Column("hashed_key", sa.String(length=128), nullable=False),
        sa.Column("source_system", sa.String(length=150), nullable=True),
        sa.Column("allowed_directions", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("allowed_models", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("hashed_key"),
    )
    op.create_index(op.f("ix_api_keys_key_prefix"), "api_keys", ["key_prefix"])

    op.add_column("transactions", sa.Column("auth_type", sa.String(length=50), nullable=True))
    op.add_column("transactions", sa.Column("api_key_id", sa.Uuid(), nullable=True))
    op.add_column("transactions", sa.Column("user_id", sa.Uuid(), nullable=True))
    op.create_foreign_key("fk_transactions_api_key_id", "transactions", "api_keys", ["api_key_id"], ["id"])
    op.create_foreign_key("fk_transactions_user_id", "transactions", "users", ["user_id"], ["id"])


def downgrade() -> None:
    op.drop_constraint("fk_transactions_user_id", "transactions", type_="foreignkey")
    op.drop_constraint("fk_transactions_api_key_id", "transactions", type_="foreignkey")
    op.drop_column("transactions", "user_id")
    op.drop_column("transactions", "api_key_id")
    op.drop_column("transactions", "auth_type")
    op.drop_index(op.f("ix_api_keys_key_prefix"), table_name="api_keys")
    op.drop_table("api_keys")

"""create transactions table

Revision ID: 202605300004
Revises: 202605300003
Create Date: 2026-05-30 00:04:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "202605300004"
down_revision: Union[str, None] = "202605300003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "transactions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("direction", sa.String(length=50), nullable=False),
        sa.Column("protocol", sa.String(length=50), nullable=False),
        sa.Column("data_model_id", sa.Uuid(), nullable=True),
        sa.Column("endpoint", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("request_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("response_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("source_system", sa.String(length=150), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["data_model_id"], ["data_models.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_transactions_created_at", "transactions", ["created_at"])
    op.create_index("ix_transactions_status", "transactions", ["status"])


def downgrade() -> None:
    op.drop_index("ix_transactions_status", table_name="transactions")
    op.drop_index("ix_transactions_created_at", table_name="transactions")
    op.drop_table("transactions")

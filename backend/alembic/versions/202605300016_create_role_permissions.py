"""create role_permissions table (prompt 34 RBAC capability layer)

Revision ID: 202605300016
Revises: 202605300015
Create Date: 2026-06-10 09:00:00

One row per (role, permission_key) with an ``allowed`` flag — the role→can-do layer enforced by
require_permission. ``admin`` is implicit-full and stored with no rows. down_revision = 015 keeps a
single alembic head.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "202605300016"
down_revision: Union[str, None] = "202605300015"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "role_permissions",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("role", sa.String(length=50), nullable=False),
        sa.Column("permission_key", sa.String(length=100), nullable=False),
        sa.Column("allowed", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("role", "permission_key", name="uq_role_permission"),
    )
    op.create_index("ix_role_permissions_role", "role_permissions", ["role"])


def downgrade() -> None:
    op.drop_index("ix_role_permissions_role", table_name="role_permissions")
    op.drop_table("role_permissions")

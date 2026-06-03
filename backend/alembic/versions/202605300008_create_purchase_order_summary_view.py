"""create purchase order summary view

Revision ID: 202605300008
Revises: 202605300007
Create Date: 2026-05-30 00:08:00
"""

from typing import Sequence, Union

from alembic import op

from app.services.procurement_staging_service import create_purchase_order_summary_view


revision: str = "202605300008"
down_revision: Union[str, None] = "202605300007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    create_purchase_order_summary_view(op.get_bind())


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS mdp_staging.vw_jde_purchase_order_summary")

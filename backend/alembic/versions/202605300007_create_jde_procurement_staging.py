"""create jde procurement staging

Revision ID: 202605300007
Revises: 202605300006
Create Date: 2026-05-30 00:07:00
"""

from typing import Sequence, Union

from alembic import op

from app.services.procurement_staging_service import seed_procurement_staging_data


revision: str = "202605300007"
down_revision: Union[str, None] = "202605300006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    seed_procurement_staging_data(op.get_bind())


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS mdp_staging.stg_jde_ap_invoice")
    op.execute("DROP TABLE IF EXISTS mdp_staging.stg_jde_po_receipt")
    op.execute("DROP TABLE IF EXISTS mdp_staging.stg_jde_po_line")
    op.execute("DROP TABLE IF EXISTS mdp_staging.stg_jde_po_header")
    op.execute("DROP TABLE IF EXISTS mdp_staging.stg_jde_supplier")
    op.execute("DROP SCHEMA IF EXISTS mdp_staging")

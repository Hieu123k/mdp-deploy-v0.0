"""add classification fields to data models

Revision ID: 202605300009
Revises: 202605300008
Create Date: 2026-05-30 00:09:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "202605300009"
down_revision = "202605300008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("data_models", sa.Column("namespace", sa.String(length=255), nullable=True))
    op.add_column("data_models", sa.Column("domain", sa.String(length=100), nullable=True))
    op.add_column("data_models", sa.Column("entity_type", sa.String(length=150), nullable=True))
    op.add_column("data_models", sa.Column("business_process", sa.String(length=100), nullable=True))
    op.add_column("data_models", sa.Column("source_layer", sa.String(length=100), nullable=True))
    op.add_column("data_models", sa.Column("canonical_status", sa.String(length=100), nullable=True))
    op.add_column("data_models", sa.Column("site_scope", sa.String(length=100), nullable=True))
    op.execute(
        """
        UPDATE data_models
        SET domain = 'procurement'
        WHERE domain IS NULL AND category = 'procurement'
        """
    )
    op.execute(
        """
        UPDATE data_models
        SET source_layer = 'generated_table'
        WHERE source_layer IS NULL AND type = 'A'
        """
    )
    op.execute(
        """
        UPDATE data_models
        SET source_layer = CASE
            WHEN attributes->0->>'source_table' LIKE 'stg_%' THEN 'staging'
            WHEN attributes->0->>'source_table' LIKE 'vw_%' THEN 'curated_view'
            ELSE source_layer
        END
        WHERE source_layer IS NULL
          AND type = 'B'
          AND jsonb_typeof(attributes) = 'array'
          AND jsonb_array_length(attributes) > 0
        """
    )
    op.execute(
        """
        UPDATE data_models
        SET canonical_status = 'experimental'
        WHERE canonical_status IS NULL
        """
    )
    op.execute(
        """
        UPDATE data_models
        SET site_scope = 'enterprise'
        WHERE site_scope IS NULL
        """
    )


def downgrade() -> None:
    op.drop_column("data_models", "site_scope")
    op.drop_column("data_models", "canonical_status")
    op.drop_column("data_models", "source_layer")
    op.drop_column("data_models", "business_process")
    op.drop_column("data_models", "entity_type")
    op.drop_column("data_models", "domain")
    op.drop_column("data_models", "namespace")

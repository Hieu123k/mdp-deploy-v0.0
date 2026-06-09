"""merge heads: streaming (202605300013) + ui-bundle user_preferences (202605300014)

Both 013 and 014 branch from 012; this no-op merge unifies them into a single head so
`alembic upgrade head` applies both. Integration build only (prompts 27 + 28 deployed together).

Revision ID: 202605300015
Revises: 202605300013, 202605300014
Create Date: 2026-06-09 15:00:00
"""

from typing import Sequence, Union


revision: str = "202605300015"
down_revision: Union[str, Sequence[str], None] = ("202605300013", "202605300014")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass

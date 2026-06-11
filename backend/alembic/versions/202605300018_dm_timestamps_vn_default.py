"""dm_* created_at/updated_at default → local (VN) wall-clock (prompt 39)

Postgres on the VM runs in UTC, so dm_* business timestamps were stored in UTC. This migration
ALTERs every existing ``mdp_data.dm_*`` table's ``created_at``/``updated_at`` DEFAULT to
``now() AT TIME ZONE '<APP_TIMEZONE>'`` (local wall-clock in a naive TIMESTAMP). It only changes the
DEFAULT — it NEVER touches existing rows (historical backfill is a separate, admin-run, gated script).

Idempotent (ALTER … SET DEFAULT is). down_revision=017 keeps a single alembic head. The timezone is
validated (regex + pg_timezone_names) before it is interpolated into DDL (anti-injection).
"""
import re
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

from app.core.config import settings


revision: str = "202605300018"
down_revision: Union[str, None] = "202605300017"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TZ_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_+/\-]*$")
_DM_TABLE_RE = re.compile(r"^dm_[a-z0-9_]*$")


def _validated_tz(conn) -> str:
    tz = settings.app_timezone
    if not tz or not _TZ_RE.fullmatch(tz):
        raise ValueError(f"Invalid APP_TIMEZONE (not a timezone name): {tz!r}")
    if not conn.execute(text("SELECT 1 FROM pg_timezone_names WHERE name = :tz"), {"tz": tz}).scalar():
        raise ValueError(f"Unknown timezone (not in pg_timezone_names): {tz}")
    return tz


def _set_dm_defaults(default_expr: str) -> None:
    conn = op.get_bind()
    if conn.dialect.name != "postgresql":
        return  # dm_* tables are postgres-only
    rows = conn.execute(
        text(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'mdp_data' AND table_name LIKE 'dm\\_%' ESCAPE '\\'"
        )
    ).fetchall()
    for (table_name,) in rows:
        if not _DM_TABLE_RE.fullmatch(table_name):  # defence even though source is information_schema
            continue
        for col in ("created_at", "updated_at"):
            conn.execute(
                text(f'ALTER TABLE "mdp_data"."{table_name}" ALTER COLUMN "{col}" SET DEFAULT {default_expr}')
            )


def upgrade() -> None:
    conn = op.get_bind()
    if conn.dialect.name != "postgresql":
        return
    tz = _validated_tz(conn)
    _set_dm_defaults(f"(now() AT TIME ZONE '{tz}')")


def downgrade() -> None:
    # Revert dm_* defaults to UTC now().
    _set_dm_defaults("now()")

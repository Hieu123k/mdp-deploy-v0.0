"""Migration Dashboard v0.0 — config-driven catalog of JDE tables that can be
migrated with ora2pg, plus the dynamic ora2pg.conf generator.

Design 1B: ora2pg loads Oracle JDE -> MDP's own PostgreSQL, schema `mdp_staging`
(no separate DW, no FDW). All credentials come from settings/env (never hardcoded).
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.engine.url import make_url

from app.core.config import settings


@dataclass(frozen=True)
class Ora2pgTable:
    """One migrate-able JDE table/view."""

    table: str               # Oracle object name (view), e.g. V2_PRO_F0911
    label: str               # human label for the dashboard dropdown
    module: str              # JDE functional module (used to group the dropdown)
    ts_col: str | None = None  # watermark column for incremental sync (None = full-load)

    @property
    def target_table(self) -> str:
        """Lower-cased target table name in mdp_staging (matches existing mirror naming)."""
        return self.table.lower()


# Single source of truth: the finalized 40-table JDE catalog (Option A — Oracle views
# V2_PRO_*). The JSON lives in the repo next to this module so the list can be regenerated
# without touching execution logic. ts_col is only known for F0911/F0411/F4311 (the rest
# full-load). `build_ora2pg_conf` does NOT use ts_col, so adding tables changes nothing there.
_CATALOG_PATH = Path(__file__).with_name("jde_migrate_tables.json")


def _rows_to_tables(rows: list[dict]) -> list[Ora2pgTable]:
    return [
        Ora2pgTable(
            table=row["source_view"],
            label=f'{row["table_id"]} — {row["name"]}',
            module=row["module"],
            ts_col=row.get("ts_col"),
        )
        for row in rows
    ]


def _load_catalog() -> list[Ora2pgTable]:
    data = json.loads(_CATALOG_PATH.read_text(encoding="utf-8"))
    tables = _rows_to_tables(data["tables"])

    # Optional environment-specific extra catalog (e.g. sandbox test fixtures) — appended at
    # import time, never written into the repo catalog. Unknown/missing file = built-in only.
    extra_path = (settings.ora2pg_extra_catalog or "").strip()
    if extra_path and Path(extra_path).is_file():
        try:
            extra = json.loads(Path(extra_path).read_text(encoding="utf-8"))
            known = {t.table.upper() for t in tables}
            for t in _rows_to_tables(extra.get("tables", [])):
                if t.table.upper() not in known:
                    tables.append(t)
                    known.add(t.table.upper())
        except Exception:  # a malformed extra catalog must never break startup
            pass
    return tables


MIGRATABLE_TABLES: list[Ora2pgTable] = _load_catalog()

_BY_NAME = {t.table.upper(): t for t in MIGRATABLE_TABLES}


def get_table(name: str) -> Ora2pgTable | None:
    return _BY_NAME.get((name or "").upper())


def _pg_target_parts() -> dict[str, str]:
    """Derive ora2pg's PostgreSQL target from the app's own DATABASE_URL.

    Design 1B: the target is MDP's own postgres (host `postgres` inside the compose
    network), schema `mdp_staging`.
    """
    url = make_url(settings.database_url)
    return {
        "host": url.host or "postgres",
        "port": str(url.port or 5432),
        "dbname": url.database or "mdp",
        "user": url.username or "mdp_user",
        "pwd": settings.postgres_password or (url.password or ""),
    }


def build_ora2pg_conf(
    table: Ora2pgTable,
    *,
    test_rows: int = 0,
    truncate: bool = True,
    where_clause: str | None = None,
    insert_on_conflict: bool = False,
    replace_target: str | None = None,
) -> str:
    """Render an ora2pg.conf for one table (mirrors tools/ora2pg migrate.sh dynamic config).

    Returns the full config text. Credentials come from settings/env. The returned
    text DOES contain runtime secrets and must only be written to the (gitignored)
    shared volume — never logged or committed. Use `redact_conf()` for logging.

    Repair-delta modes (additive, defaults preserve the original full-load output):
    ``truncate=False`` emits ``TRUNCATE_TABLE 0`` so the export *appends* instead of
    wiping the table; ``where_clause`` injects an ora2pg ``WHERE`` directive (e.g.
    ``V2_PRO_F0911[UPMJ >= 124001]``) to re-pull only a watermark range;
    ``insert_on_conflict=True`` emits ``INSERT_ON_CONFLICT 1`` so an ``-t INSERT`` pass
    becomes ``INSERT … ON CONFLICT DO NOTHING`` — with a UNIQUE index on the target PK
    this re-pulls the whole source but inserts only the rows that are missing (PK repair).
    """
    pg = _pg_target_parts()
    oracle_dsn = f"dbi:Oracle:host={settings.oracle_host};port={settings.oracle_port}"
    if settings.oracle_service_name:
        oracle_dsn += f";service_name={settings.oracle_service_name}"
    elif settings.oracle_sid:
        oracle_dsn += f";sid={settings.oracle_sid}"

    lines = [
        f"ORACLE_DSN       {oracle_dsn}",
        f"ORACLE_USER      {settings.oracle_user}",
        f"ORACLE_PWD       {settings.oracle_pwd}",
        "",
        f"PG_DSN           dbi:Pg:dbname={pg['dbname']};host={pg['host']};port={pg['port']}",
        f"PG_USER          {pg['user']}",
        f"PG_PWD           {pg['pwd']}",
        f"PG_SCHEMA        {settings.ora2pg_target_schema}",
        "PG_VERSION       16",
        "",
        f"SCHEMA           {settings.oracle_schema}",
        f"ALLOW            {table.table}",
        f"MODIFY_TYPE      {table.table}:*:text",
        f"VIEW_AS_TABLE    {table.table}",
        "EXPORT_SCHEMA    0",
        "CREATE_SCHEMA    0",
        "DEFAULT_NUMERIC  numeric",
        "DROP_IF_EXISTS   1",
        f"TRUNCATE_TABLE   {1 if truncate else 0}",
        "PRESERVE_CASE    0",
        "DISABLE_TRIGGERS 1",
        "DROP_FKEY        0",
        f"DATA_LIMIT       {settings.ora2pg_data_limit}",
        "LONGREADLEN      1048576",
        "PARALLEL_TABLES  1",
        "JOBS             4",
        "ORACLE_COPIES    4",
        "FILE_PER_TABLE   1",
        "NULLIF           ''",
    ]
    if insert_on_conflict:
        lines.append("INSERT_ON_CONFLICT 1")
    if replace_target:
        # Redirect ora2pg's PG output table name (default = lower(view)) to a different table — used
        # by the Case-B full-reload to load into <target>_new before an atomic swap. Source view
        # (ALLOW/VIEW_AS_TABLE) is unchanged; only the OUTPUT table name is renamed.
        lines.append(f"REPLACE_TABLES   {table.table}:{replace_target}")
    if where_clause:
        lines.append(f"WHERE            {where_clause}")
    elif test_rows and test_rows > 0:
        lines.append(f"WHERE            ROWNUM <= {int(test_rows)}")
    return "\n".join(lines) + "\n"


def redact_conf(conf_text: str) -> str:
    """Mask secret values (ORACLE_PWD / PG_PWD / passwords inside DSNs) for safe logging."""
    out: list[str] = []
    for line in conf_text.splitlines():
        key = line.split(maxsplit=1)[0] if line.strip() else ""
        if key in {"ORACLE_PWD", "PG_PWD"}:
            out.append(f"{key}       ***")
        else:
            out.append(line)
    return "\n".join(out)

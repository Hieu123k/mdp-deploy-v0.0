"""Migration Dashboard v0.0 — config-driven catalog of JDE tables that can be
migrated with ora2pg, plus the dynamic ora2pg.conf generator.

Design 1B: ora2pg loads Oracle JDE -> MDP's own PostgreSQL, schema `mdp_staging`
(no separate DW, no FDW). All credentials come from settings/env (never hardcoded).
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.engine.url import make_url

from app.core.config import settings


@dataclass(frozen=True)
class Ora2pgTable:
    """One migrate-able JDE table/view."""

    table: str          # Oracle object name, e.g. V2_PRO_F0911
    ts_col: str          # timestamp/watermark column used for incremental sync
    label: str           # human label for the dashboard dropdown

    @property
    def target_table(self) -> str:
        """Lower-cased target table name in mdp_staging (matches existing mirror naming)."""
        return self.table.lower()


# Config-driven list of supported tables (F0911:upmj, F0411:rpupmj, F4311:pdupmj).
# Extend here without touching execution logic.
MIGRATABLE_TABLES: list[Ora2pgTable] = [
    Ora2pgTable(table="V2_PRO_F0911", ts_col="upmj", label="F0911 — Account Ledger"),
    Ora2pgTable(table="V2_PRO_F0411", ts_col="rpupmj", label="F0411 — Accounts Payable Ledger"),
    Ora2pgTable(table="V2_PRO_F4311", ts_col="pdupmj", label="F4311 — Purchase Order Detail"),
]

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


def build_ora2pg_conf(table: Ora2pgTable, *, test_rows: int = 0) -> str:
    """Render an ora2pg.conf for one table (mirrors tools/ora2pg migrate.sh dynamic config).

    Returns the full config text. Credentials come from settings/env. The returned
    text DOES contain runtime secrets and must only be written to the (gitignored)
    shared volume — never logged or committed. Use `redact_conf()` for logging.
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
        "TRUNCATE_TABLE   1",
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
    if test_rows and test_rows > 0:
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

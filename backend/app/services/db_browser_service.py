import re
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session


IDENTIFIER_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")
SYSTEM_SCHEMAS = {"pg_catalog", "information_schema", "pg_toast"}
DEFAULT_SCHEMAS = ["public", "mdp_data", "mdp_staging"]


class DbBrowserValidationError(Exception):
    pass


class DbBrowserNotFoundError(Exception):
    pass


def validate_identifier(identifier: str, label: str) -> None:
    if not IDENTIFIER_PATTERN.fullmatch(identifier):
        raise DbBrowserValidationError(
            f"{label} must be a lowercase snake_case identifier"
        )


def _dialect_name(db: Session) -> str:
    return db.bind.dialect.name


def _qualified_table(schema_name: str, table_name: str, dialect_name: str) -> str:
    if dialect_name == "postgresql":
        return f"{schema_name}.{table_name}"
    return table_name


def list_schemas(db: Session) -> list[str]:
    dialect_name = _dialect_name(db)
    if dialect_name != "postgresql":
        return DEFAULT_SCHEMAS

    rows = db.execute(
        text(
            """
            SELECT schema_name
            FROM information_schema.schemata
            WHERE schema_name NOT IN ('pg_catalog', 'information_schema', 'pg_toast')
              AND schema_name NOT LIKE 'pg_temp_%'
              AND schema_name NOT LIKE 'pg_toast_temp_%'
            ORDER BY schema_name
            """
        )
    ).scalars()
    schemas = [schema for schema in rows if schema not in SYSTEM_SCHEMAS]
    ordered_defaults = [schema for schema in DEFAULT_SCHEMAS if schema in schemas]
    extras = [schema for schema in schemas if schema not in ordered_defaults]
    return ordered_defaults + extras


def schema_exists(db: Session, schema_name: str) -> bool:
    validate_identifier(schema_name, "schema_name")
    if schema_name.startswith("pg_") or schema_name in SYSTEM_SCHEMAS:
        return False
    if _dialect_name(db) != "postgresql":
        return schema_name in DEFAULT_SCHEMAS

    result = db.execute(
        text("SELECT 1 FROM information_schema.schemata WHERE schema_name = :schema"),
        {"schema": schema_name},
    )
    return result.first() is not None


def ensure_schema_exists(db: Session, schema_name: str) -> None:
    if not schema_exists(db, schema_name):
        raise DbBrowserNotFoundError(f"Schema not found: {schema_name}")


def list_tables(db: Session, schema_name: str) -> list[dict[str, str]]:
    ensure_schema_exists(db, schema_name)
    dialect_name = _dialect_name(db)
    if dialect_name != "postgresql":
        rows = db.execute(
            text(
                """
                SELECT name, type
                FROM sqlite_master
                WHERE type IN ('table', 'view')
                ORDER BY name
                """
            )
        ).mappings()
        return [
            {
                "table_name": row["name"],
                "table_type": "VIEW" if row["type"] == "view" else "BASE TABLE",
            }
            for row in rows
            if schema_name != "mdp_staging"
            or row["name"].startswith("stg_")
            or row["name"].startswith("vw_")
        ]

    rows = db.execute(
        text(
            """
            SELECT table_name, table_type
            FROM information_schema.tables
            WHERE table_schema = :schema
            ORDER BY table_name
            """
        ),
        {"schema": schema_name},
    ).mappings()
    return [
        {"table_name": row["table_name"], "table_type": row["table_type"]}
        for row in rows
    ]


def table_exists(db: Session, schema_name: str, table_name: str) -> bool:
    validate_identifier(table_name, "table_name")
    ensure_schema_exists(db, schema_name)
    dialect_name = _dialect_name(db)
    if dialect_name != "postgresql":
        result = db.execute(
            text("SELECT 1 FROM sqlite_master WHERE type IN ('table', 'view') AND name = :table"),
            {"table": table_name},
        )
        return result.first() is not None

    result = db.execute(
        text(
            """
            SELECT 1
            FROM information_schema.tables
            WHERE table_schema = :schema AND table_name = :table
            """
        ),
        {"schema": schema_name, "table": table_name},
    )
    return result.first() is not None


def ensure_table_exists(db: Session, schema_name: str, table_name: str) -> None:
    if not table_exists(db, schema_name, table_name):
        raise DbBrowserNotFoundError(f"Table not found: {schema_name}.{table_name}")


def _sqlite_column_type(column_name: str, declared_type: str | None) -> str:
    if declared_type:
        return declared_type.lower()
    if column_name in {"line_count", "open_line_count", "invoice_count", "line_no"}:
        return "integer"
    if (
        column_name.startswith("total_")
        or column_name.endswith("_amount")
        or column_name.endswith("_quantity")
        or column_name in {"quantity_ordered", "quantity_received", "unit_cost", "line_amount"}
    ):
        return "double precision"
    if column_name.endswith("_date"):
        return "date"
    if column_name.endswith("_at"):
        return "timestamp"
    return "text"


def list_columns(db: Session, schema_name: str, table_name: str) -> list[dict[str, Any]]:
    ensure_table_exists(db, schema_name, table_name)
    dialect_name = _dialect_name(db)
    if dialect_name != "postgresql":
        rows = db.execute(text(f"PRAGMA table_info({table_name})")).mappings()
        return [
            {
                "column_name": row["name"],
                "data_type": _sqlite_column_type(row["name"], row["type"]),
                "is_nullable": "NO" if row["notnull"] or row["pk"] else "YES",
                "ordinal_position": row["cid"] + 1,
                "column_default": row["dflt_value"],
            }
            for row in rows
        ]

    rows = db.execute(
        text(
            """
            SELECT column_name, data_type, is_nullable, ordinal_position, column_default
            FROM information_schema.columns
            WHERE table_schema = :schema AND table_name = :table
            ORDER BY ordinal_position
            """
        ),
        {"schema": schema_name, "table": table_name},
    ).mappings()
    return [dict(row) for row in rows]


def serialize_value(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return value


# Hard ceiling for a single page (incl. the "All" selector) — NEVER SELECT a whole multi-million
# -row table at once (e.g. F4111 ~58M would OOM the browser/backend). "All" caps here + paginates.
PREVIEW_MAX_LIMIT = 10_000


def _estimate_row_total(db: Session, schema_name: str, table_name: str, dialect_name: str) -> int | None:
    """O(1) planner-stat estimate of total rows (Postgres reltuples) so a pager has a denominator
    WITHOUT a full count(*) on a huge table. None on SQLite / when unknown."""
    if dialect_name != "postgresql":
        return None
    try:
        val = db.execute(
            text("SELECT reltuples::bigint FROM pg_class WHERE oid = to_regclass(:rel)"),
            {"rel": f"{schema_name}.{table_name}"},
        ).scalar()
        return int(val) if val is not None and val >= 0 else None
    except Exception:
        return None


def preview_table(
    db: Session,
    schema_name: str,
    table_name: str,
    *,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    ensure_table_exists(db, schema_name, table_name)
    limit = min(max(limit, 1), PREVIEW_MAX_LIMIT)  # raised cap (was 100) so 500/1000/All work, but bounded
    offset = max(offset, 0)
    columns = [column["column_name"] for column in list_columns(db, schema_name, table_name)]
    dialect_name = _dialect_name(db)
    table_ref = _qualified_table(schema_name, table_name, dialect_name)
    # Pull limit+1 to know if there's a next page without counting the whole table.
    rows = db.execute(
        text(f"SELECT * FROM {table_ref} LIMIT :limit OFFSET :offset"),
        {"limit": limit + 1, "offset": offset},
    ).mappings()
    data = [
        {key: serialize_value(value) for key, value in row.items()}
        for row in rows
    ]
    has_more = len(data) > limit
    data = data[:limit]
    return {
        "schema": schema_name,
        "table": table_name,
        "limit": limit,
        "offset": offset,
        "count": len(data),
        "has_more": has_more,
        "total_estimate": _estimate_row_total(db, schema_name, table_name, dialect_name),
        "max_limit": PREVIEW_MAX_LIMIT,
        "columns": columns,
        "rows": data,
    }

import re
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings


SYSTEM_COLUMN_NAMES = {"id", "raw_payload", "created_at", "updated_at"}
IDENTIFIER_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")
# IANA tz names are letters/digits and a small set of separators (e.g. Asia/Ho_Chi_Minh, Etc/GMT+7).
# This pre-filter makes injection impossible BEFORE the pg_timezone_names existence check.
TIMEZONE_NAME_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_+/\-]*$")

DATA_TYPE_TO_POSTGRES = {
    "text": "TEXT",
    "integer": "INTEGER",
    "float": "DOUBLE PRECISION",
    "boolean": "BOOLEAN",
    "date": "DATE",
    "datetime": "TIMESTAMP",
    "json": "JSONB",
}


class TableGenerationError(Exception):
    pass


def validate_identifier(identifier: str, label: str) -> None:
    if not IDENTIFIER_PATTERN.fullmatch(identifier):
        raise TableGenerationError(f"{label} must be lowercase snake_case")


def ensure_mdp_data_schema_exists(db: Session) -> None:
    if db.bind and db.bind.dialect.name != "postgresql":
        return
    db.execute(text('CREATE SCHEMA IF NOT EXISTS "mdp_data"'))


def get_generated_table_name(model_name: str) -> str:
    validate_identifier(model_name, "Data model name")
    return f"mdp_data.dm_{model_name}"


def quote_identifier(identifier: str) -> str:
    validate_identifier(identifier, "Identifier")
    return f'"{identifier}"'


def validate_timezone(db: Session, tz: str) -> str:
    """Validate a timezone name BEFORE it is interpolated into DDL (anti-injection). It must match the
    safe IANA pattern AND — on postgres — exist in ``pg_timezone_names``. Returns the validated name
    (safe to embed). A toxic/unknown ``APP_TIMEZONE`` raises ``TableGenerationError`` rather than
    reaching SQL."""
    if not tz or not TIMEZONE_NAME_PATTERN.fullmatch(tz):
        raise TableGenerationError(f"Invalid APP_TIMEZONE (not a timezone name): {tz!r}")
    if db.bind and db.bind.dialect.name == "postgresql":
        exists = db.execute(
            text("SELECT 1 FROM pg_timezone_names WHERE name = :tz"), {"tz": tz}
        ).scalar()
        if not exists:
            raise TableGenerationError(f"Unknown timezone (not in pg_timezone_names): {tz}")
    return tz


def timestamp_default_clause(db: Session, tz: str | None = None) -> str:
    """DEFAULT expression for dm_* ``created_at``/``updated_at``: VN wall-clock stored in a NAIVE
    ``TIMESTAMP`` column. Postgres on the VM is UTC, so ``now() AT TIME ZONE '<tz>'`` shifts UTC →
    the configured local wall-clock. ``tz`` defaults to ``settings.app_timezone``; it is validated."""
    safe_tz = validate_timezone(db, tz or settings.app_timezone)
    return f"(now() AT TIME ZONE '{safe_tz}')"


def map_data_type_to_postgres(data_type: str) -> str:
    try:
        return DATA_TYPE_TO_POSTGRES[data_type]
    except KeyError as exc:
        raise TableGenerationError(f"Unsupported data type: {data_type}") from exc


def validate_generated_column_names(attributes: list[dict[str, Any]]) -> None:
    seen: set[str] = set()
    for attribute in attributes:
        name = attribute["name"]
        validate_identifier(name, "Attribute name")
        if name in SYSTEM_COLUMN_NAMES:
            raise TableGenerationError(
                f"Attribute name conflicts with system column: {name}"
            )
        if name in seen:
            raise TableGenerationError(f"Duplicate attribute name: {name}")
        seen.add(name)


def generated_table_exists(db: Session, model_name: str) -> bool:
    if db.bind and db.bind.dialect.name != "postgresql":
        return False

    table_name = get_generated_table_name(model_name)
    result = db.execute(
        text("SELECT to_regclass(:table_name) IS NOT NULL"),
        {"table_name": table_name},
    )
    return bool(result.scalar())


def create_generated_table_for_model(db: Session, model: Any) -> str:
    table_name = get_generated_table_name(model.name)
    validate_generated_column_names(model.attributes)
    # Validate the timezone up-front (before the dialect branch) so a toxic APP_TIMEZONE is rejected
    # on every backend, not only postgres.
    tz_default = timestamp_default_clause(db)

    if db.bind and db.bind.dialect.name != "postgresql":
        return table_name

    ensure_mdp_data_schema_exists(db)
    schema_name, bare_table_name = table_name.split(".", 1)
    quoted_table_name = f'{quote_identifier(schema_name)}.{quote_identifier(bare_table_name)}'

    columns = [
        '"id" UUID PRIMARY KEY',
        '"raw_payload" JSONB NULL',
        # NAIVE timestamp storing local (VN) wall-clock — Postgres is UTC, the default shifts it.
        f'"created_at" TIMESTAMP DEFAULT {tz_default}',
        f'"updated_at" TIMESTAMP DEFAULT {tz_default}',
    ]
    for attribute in model.attributes:
        column_name = quote_identifier(attribute["name"])
        column_type = map_data_type_to_postgres(attribute["data_type"])
        columns.append(f"{column_name} {column_type}")

    # IF NOT EXISTS: a model can be hard-deleted while its generated table is intentionally KEPT
    # (data-safety). Re-creating a model with the same name REUSES that orphan table — never drops it
    # — so existing data survives. (New attribute columns on a reused table are added later via
    # sync_generated_table_columns / update; this call never drops or truncates.)
    db.execute(text(f"CREATE TABLE IF NOT EXISTS {quoted_table_name} ({', '.join(columns)})"))
    return table_name


def sync_generated_table_columns(db: Session, model: Any) -> list[str]:
    """Keep a Type A model's physical generated table in sync with its attributes by ADDING
    any column the model now declares but the table is missing.

    Non-destructive on purpose: it never drops or renames columns, so editing a model can't
    lose data, and the physical table is always a superset of the attribute columns — which is
    what ``insert_inbound_record`` needs (it builds its column list from the attributes; a
    missing column would make every inbound insert fail). A removed/renamed attribute simply
    leaves an unused column behind. Returns the names of the columns that were added.
    """
    if db.bind and db.bind.dialect.name != "postgresql":
        return []
    if not generated_table_exists(db, model.name):
        return []
    validate_generated_column_names(model.attributes)
    table_name = get_generated_table_name(model.name)
    schema_name, bare_table_name = table_name.split(".", 1)
    existing = {
        row[0]
        for row in db.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = :schema AND table_name = :table"
            ),
            {"schema": schema_name, "table": bare_table_name},
        )
    }
    quoted_table_name = f"{quote_identifier(schema_name)}.{quote_identifier(bare_table_name)}"
    added: list[str] = []
    for attribute in model.attributes:
        name = attribute["name"]
        if name in SYSTEM_COLUMN_NAMES or name in existing:
            continue
        column_type = map_data_type_to_postgres(attribute["data_type"])
        db.execute(
            text(f"ALTER TABLE {quoted_table_name} ADD COLUMN IF NOT EXISTS {quote_identifier(name)} {column_type}")
        )
        added.append(name)
    return added

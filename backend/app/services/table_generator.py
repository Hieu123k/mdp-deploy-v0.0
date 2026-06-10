import re
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session


SYSTEM_COLUMN_NAMES = {"id", "raw_payload", "created_at", "updated_at"}
IDENTIFIER_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")

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

    if db.bind and db.bind.dialect.name != "postgresql":
        return table_name

    ensure_mdp_data_schema_exists(db)
    schema_name, bare_table_name = table_name.split(".", 1)
    quoted_table_name = f'{quote_identifier(schema_name)}.{quote_identifier(bare_table_name)}'

    columns = [
        '"id" UUID PRIMARY KEY',
        '"raw_payload" JSONB NULL',
        '"created_at" TIMESTAMP DEFAULT now()',
        '"updated_at" TIMESTAMP DEFAULT now()',
    ]
    for attribute in model.attributes:
        column_name = quote_identifier(attribute["name"])
        column_type = map_data_type_to_postgres(attribute["data_type"])
        columns.append(f"{column_name} {column_type}")

    # IF NOT EXISTS: a model can be hard-deleted while its generated table is intentionally KEPT
    # (data-safety). Re-creating a model with the same name must REUSE that table — never drop it —
    # so existing data survives; sync_generated_table_columns then adds any new attribute columns.
    db.execute(text(f"CREATE TABLE IF NOT EXISTS {quoted_table_name} ({', '.join(columns)})"))
    sync_generated_table_columns(db, model)
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

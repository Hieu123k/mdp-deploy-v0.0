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

    db.execute(text(f"CREATE TABLE {quoted_table_name} ({', '.join(columns)})"))
    return table_name

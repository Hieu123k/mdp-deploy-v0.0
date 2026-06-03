from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.data_model import DataModel
from app.schemas.data_model import DataModelCreate
from app.services.db_browser_service import (
    DbBrowserNotFoundError,
    DbBrowserValidationError,
    list_columns,
    serialize_value,
    validate_identifier,
)


ALLOWED_TYPE_B_SCHEMAS = {"mdp_staging", "public", "mdp_data"}
VIEW_PRIMARY_KEY_WARNING = (
    "Primary key source column is from a view. Nullability cannot be reliably "
    "enforced by information_schema."
)
NULLABLE_PRIMARY_KEY_WARNING = (
    "Primary key source column is nullable. Ensure values are unique and not null."
)
PRIMARY_KEY_NULL_VALUES_WARNING = "Primary key source column contains null values."
POSTGRES_TO_PLATFORM_TYPES = {
    "text": "text",
    "character varying": "text",
    "varchar": "text",
    "character": "text",
    "char": "text",
    "integer": "integer",
    "bigint": "integer",
    "smallint": "integer",
    "numeric": "float",
    "double precision": "float",
    "real": "float",
    "decimal": "float",
    "boolean": "boolean",
    "date": "date",
    "timestamp": "datetime",
    "timestamp without time zone": "datetime",
    "timestamp with time zone": "datetime",
    "json": "json",
    "jsonb": "json",
}


class TypeBMappingError(Exception):
    def __init__(self, errors: list[dict[str, str]]) -> None:
        self.errors = errors
        super().__init__("Type B mapping validation failed")


def _dialect_name(db: Session) -> str:
    return db.bind.dialect.name


def _qualified_table(schema_name: str, table_name: str, dialect_name: str) -> str:
    if dialect_name == "postgresql":
        return f"{schema_name}.{table_name}"
    return table_name


def _attribute_payload(attribute: Any) -> dict[str, Any]:
    return attribute.model_dump(exclude_none=True) if hasattr(attribute, "model_dump") else dict(attribute)


def _normalize_postgres_type(data_type: str) -> str | None:
    normalized = data_type.lower()
    if normalized.startswith("character varying"):
        normalized = "character varying"
    if normalized.startswith("timestamp with time zone"):
        normalized = "timestamp with time zone"
    if normalized.startswith("timestamp without time zone"):
        normalized = "timestamp without time zone"
    if normalized.startswith("timestamp"):
        normalized = "timestamp"
    if normalized.startswith("numeric") or normalized.startswith("decimal"):
        normalized = normalized.split("(")[0]
    return POSTGRES_TO_PLATFORM_TYPES.get(normalized)


def _source_columns_by_name(
    db: Session,
    source_schema: str,
    source_table: str,
) -> dict[str, dict[str, Any]]:
    try:
        columns = list_columns(db, source_schema, source_table)
    except (DbBrowserValidationError, DbBrowserNotFoundError) as exc:
        raise TypeBMappingError(
            [{"field": "source_table", "message": str(exc)}]
        ) from exc
    return {column["column_name"]: column for column in columns}


def _source_object_type(db: Session, source_schema: str, source_table: str) -> str:
    dialect_name = _dialect_name(db)
    if dialect_name == "postgresql":
        result = db.execute(
            text(
                """
                SELECT table_type
                FROM information_schema.tables
                WHERE table_schema = :schema AND table_name = :table
                """
            ),
            {"schema": source_schema, "table": source_table},
        ).scalar_one_or_none()
        return result or "UNKNOWN"

    result = db.execute(
        text("SELECT type FROM sqlite_master WHERE name = :table"),
        {"table": source_table},
    ).scalar_one_or_none()
    return "VIEW" if result == "view" else "BASE TABLE"


def _primary_key_null_count(
    db: Session,
    source_schema: str,
    source_table: str,
    source_column: str,
) -> int:
    dialect_name = _dialect_name(db)
    table_ref = _qualified_table(source_schema, source_table, dialect_name)
    result = db.execute(
        text(f"SELECT COUNT(*) FROM {table_ref} WHERE {source_column} IS NULL")
    ).scalar_one()
    return int(result)


def validate_type_b_mapping(
    db: Session,
    data_model_in: DataModelCreate,
) -> dict[str, Any]:
    errors: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []

    if data_model_in.type != "B":
        errors.append({"field": "type", "message": "Mapping validation only supports Type B models"})

    primary_attributes = [
        attribute.name for attribute in data_model_in.attributes if attribute.is_primary_key
    ]
    primary_key = data_model_in.primary_key or (primary_attributes[0] if primary_attributes else None)
    if not primary_key:
        errors.append(
            {
                "field": "primary_key",
                "message": "Type B models require primary_key or one primary key attribute",
            }
        )

    source_pairs: set[tuple[str, str]] = set()
    attribute_payloads = [_attribute_payload(attribute) for attribute in data_model_in.attributes]
    for index, attribute in enumerate(attribute_payloads):
        for field in ("name", "source_schema", "source_table", "source_column"):
            value = attribute.get(field)
            if not value:
                errors.append(
                    {
                        "field": f"attributes[{index}].{field}",
                        "message": f"Type B attributes require {field}",
                    }
                )
                continue
            try:
                validate_identifier(value, field)
            except DbBrowserValidationError as exc:
                errors.append({"field": f"attributes[{index}].{field}", "message": str(exc)})

        source_schema = attribute.get("source_schema")
        source_table = attribute.get("source_table")
        if source_schema and source_schema not in ALLOWED_TYPE_B_SCHEMAS:
            errors.append(
                {
                    "field": f"attributes[{index}].source_schema",
                    "message": "source_schema must be one of: mdp_staging, public, mdp_data",
                }
            )
        if source_schema and source_table:
            source_pairs.add((source_schema, source_table))

    if len(source_pairs) > 1:
        errors.append(
            {
                "field": "attributes",
                "message": "Type B models currently support only one source table per model.",
            }
        )

    if primary_key and primary_key not in {attribute["name"] for attribute in attribute_payloads}:
        errors.append(
            {"field": "primary_key", "message": "primary_key must match one of the attribute names"}
        )

    if errors:
        raise TypeBMappingError(errors)

    source_schema, source_table = next(iter(source_pairs))
    source_columns = _source_columns_by_name(db, source_schema, source_table)

    mapped_columns: list[dict[str, str]] = []
    mapped_attributes: set[str] = set()
    source_column_by_attribute: dict[str, dict[str, Any]] = {}
    for index, attribute in enumerate(attribute_payloads):
        source_column = attribute["source_column"]
        source_column_info = source_columns.get(source_column)
        if source_column_info is None:
            errors.append(
                {
                    "field": f"attributes[{index}].source_column",
                    "message": f"Source column not found: {source_schema}.{source_table}.{source_column}",
                }
            )
            continue

        source_platform_type = _normalize_postgres_type(source_column_info["data_type"])
        if source_platform_type is None:
            errors.append(
                {
                    "field": f"attributes[{index}].source_column",
                    "message": f"Unsupported source data type: {source_column_info['data_type']}",
                }
            )
            continue
        if source_platform_type != attribute["data_type"]:
            errors.append(
                {
                    "field": f"attributes[{index}].data_type",
                    "message": (
                        f"Declared data_type {attribute['data_type']} is incompatible with "
                        f"source column type {source_column_info['data_type']}"
                    ),
                }
            )
            continue

        mapped_columns.append(
            {
                "attribute": attribute["name"],
                "source_column": source_column,
                "source_data_type": source_column_info["data_type"],
                "model_data_type": attribute["data_type"],
            }
        )
        mapped_attributes.add(attribute["name"])
        source_column_by_attribute[attribute["name"]] = source_column_info

    if primary_key:
        primary_attribute = next(
            (attribute for attribute in attribute_payloads if attribute["name"] == primary_key),
            None,
        )
        if primary_attribute is None:
            errors.append(
                {
                    "field": "primary_key",
                    "message": "Primary key attribute must exist in attributes",
                }
            )
        elif not primary_attribute.get("source_column"):
            errors.append(
                {
                    "field": "primary_key",
                    "message": "Primary key attribute must map to a valid source_column",
                }
            )
        elif primary_key not in mapped_attributes:
            errors.append(
                {
                    "field": "primary_key",
                    "message": "Primary key attribute must map to an existing compatible source_column",
                }
            )
        else:
            source_column_info = source_column_by_attribute[primary_key]
            source_object_type = _source_object_type(db, source_schema, source_table)
            if source_object_type == "VIEW":
                warnings.append(
                    {
                        "field": "primary_key",
                        "message": VIEW_PRIMARY_KEY_WARNING,
                    }
                )
            elif source_column_info.get("is_nullable") == "YES":
                warnings.append(
                    {
                        "field": "primary_key",
                        "message": NULLABLE_PRIMARY_KEY_WARNING,
                    }
                )
            if _primary_key_null_count(
                db,
                source_schema,
                source_table,
                source_column_info["column_name"],
            ):
                warnings.append(
                    {
                        "field": "primary_key",
                        "message": PRIMARY_KEY_NULL_VALUES_WARNING,
                    }
                )

    if errors:
        raise TypeBMappingError(errors)

    return {
        "status": "success",
        "message": "Type B mapping is valid",
        "warnings": warnings,
        "source_schema": source_schema,
        "source_table": source_table,
        "mapped_columns": mapped_columns,
    }


def preview_type_b_mapping(
    db: Session,
    data_model_in: DataModelCreate,
    *,
    limit: int = 20,
    offset: int = 0,
) -> dict[str, Any]:
    validation = validate_type_b_mapping(db, data_model_in)
    return _preview_mapping(
        db,
        model_name=data_model_in.name,
        source_schema=validation["source_schema"],
        source_table=validation["source_table"],
        mapped_columns=validation["mapped_columns"],
        warnings=validation["warnings"],
        limit=limit,
        offset=offset,
    )


def preview_saved_type_b_model(
    db: Session,
    data_model: DataModel,
    *,
    limit: int = 20,
    offset: int = 0,
) -> dict[str, Any]:
    if data_model.type != "B":
        raise TypeBMappingError(
            [{"field": "type", "message": "Mapped preview is only supported for Type B data models"}]
        )
    payload = {
        "name": data_model.name,
        "display_name": data_model.display_name,
        "type": data_model.type,
        "category": data_model.category,
        "description": data_model.description,
        "business_definition": data_model.business_definition,
        "owner_department": data_model.owner_department,
        "source_system": data_model.source_system,
        "primary_key": data_model.primary_key,
        "attributes": data_model.attributes,
        "relationships": data_model.relationships,
        "refresh_policy": data_model.refresh_policy,
        "sensitivity_level": data_model.sensitivity_level,
        "ai_enabled": data_model.ai_enabled,
        "status": data_model.status,
    }
    data_model_in = DataModelCreate.model_validate(payload)
    return preview_type_b_mapping(db, data_model_in, limit=limit, offset=offset)


def _preview_mapping(
    db: Session,
    *,
    model_name: str,
    source_schema: str,
    source_table: str,
    mapped_columns: list[dict[str, str]],
    warnings: list[dict[str, str]],
    limit: int,
    offset: int,
) -> dict[str, Any]:
    limit = min(max(limit, 1), 100)
    offset = max(offset, 0)
    dialect_name = _dialect_name(db)
    table_ref = _qualified_table(source_schema, source_table, dialect_name)
    select_columns = ", ".join(
        f"{column['source_column']} AS {column['attribute']}" for column in mapped_columns
    )
    rows = db.execute(
        text(f"SELECT {select_columns} FROM {table_ref} LIMIT :limit OFFSET :offset"),
        {"limit": limit, "offset": offset},
    ).mappings()
    data = [
        {key: serialize_value(value) for key, value in row.items()}
        for row in rows
    ]
    return {
        "status": "success",
        "model": model_name,
        "source_schema": source_schema,
        "source_table": source_table,
        "warnings": warnings,
        "limit": limit,
        "offset": offset,
        "count": len(data),
        "data": data,
    }

import json
import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.models.data_model import DataModel
from app.services.api_key_service import AuthContext
from app.services.data_model_service import get_data_model_by_name
from app.services.table_generator import (
    TableGenerationError,
    get_generated_table_name,
    quote_identifier,
    validate_generated_column_names,
    validate_identifier,
)
from app.services.transaction_logger import log_transaction


class InboundValidationError(Exception):
    def __init__(self, errors: list[dict[str, str]]) -> None:
        self.errors = errors
        super().__init__("Inbound payload validation failed")


class InboundInsertError(Exception):
    pass


def get_active_data_model_by_name(db: Session, model_name: str) -> DataModel | None:
    model = get_data_model_by_name(db, model_name)
    if model is None or model.status != "active":
        return None
    return model


def validate_scalar_value(field: str, data_type: str, value: Any) -> dict[str, str] | None:
    if data_type == "text" and not isinstance(value, str):
        return {"field": field, "message": "must be a string"}
    if data_type == "integer" and not (isinstance(value, int) and not isinstance(value, bool)):
        return {"field": field, "message": "must be an integer"}
    if data_type == "float" and not (
        isinstance(value, (int, float)) and not isinstance(value, bool)
    ):
        return {"field": field, "message": "must be a number"}
    if data_type == "boolean" and not isinstance(value, bool):
        return {"field": field, "message": "must be a boolean"}
    if data_type == "date":
        if not isinstance(value, str):
            return {"field": field, "message": "must be an ISO date string"}
        try:
            date.fromisoformat(value)
        except ValueError:
            return {"field": field, "message": "must be a valid ISO date YYYY-MM-DD"}
    if data_type == "datetime":
        if not isinstance(value, str):
            return {"field": field, "message": "must be an ISO datetime string"}
        try:
            datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return {"field": field, "message": "must be a valid ISO datetime string"}
    if data_type == "json" and not isinstance(value, (dict, list)):
        return {"field": field, "message": "must be an object or array"}
    return None


def validate_inbound_payload(
    model: DataModel,
    payload: dict[str, Any],
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise InboundValidationError(
            [{"field": "body", "message": "must be a flat JSON object"}]
        )

    validate_generated_column_names(model.attributes)
    errors: list[dict[str, str]] = []
    mapped_values: dict[str, Any] = {}

    for attribute in model.attributes:
        name = attribute["name"]
        data_type = attribute["data_type"]
        required = bool(attribute.get("required", False))

        if name not in payload or payload[name] is None:
            if required:
                errors.append({"field": name, "message": "is required"})
            continue

        value = payload[name]
        error = validate_scalar_value(name, data_type, value)
        if error is not None:
            errors.append(error)
            continue
        mapped_values[name] = value

    if errors:
        raise InboundValidationError(errors)

    return mapped_values


def insert_inbound_record(
    db: Session,
    model: DataModel,
    payload: dict[str, Any],
) -> uuid.UUID:
    record_id = uuid.uuid4()
    table_name = model.generated_table or get_generated_table_name(model.name)
    schema_name, bare_table_name = table_name.split(".", 1)
    validate_identifier(model.name, "Data model name")
    validate_identifier(schema_name, "Schema name")
    validate_identifier(bare_table_name, "Table name")

    mapped_values = validate_inbound_payload(model, payload)
    is_postgres = bool(db.bind and db.bind.dialect.name == "postgresql")
    columns = ['"id"', '"raw_payload"']
    values = [":id", "CAST(:raw_payload AS JSONB)" if is_postgres else ":raw_payload"]
    params: dict[str, Any] = {
        "id": record_id if is_postgres else str(record_id),
        "raw_payload": json.dumps(payload),
    }

    for column_name, value in mapped_values.items():
        columns.append(quote_identifier(column_name))
        param_name = f"col_{column_name}"
        attribute = next(attr for attr in model.attributes if attr["name"] == column_name)
        if attribute["data_type"] == "json":
            values.append(f"CAST(:{param_name} AS JSONB)" if is_postgres else f":{param_name}")
            params[param_name] = json.dumps(value)
        else:
            values.append(f":{param_name}")
            params[param_name] = value

    quoted_table = f"{quote_identifier(schema_name)}.{quote_identifier(bare_table_name)}"
    statement = text(
        f"INSERT INTO {quoted_table} ({', '.join(columns)}) "
        f"VALUES ({', '.join(values)})"
    )
    db.execute(statement, params)
    return record_id


def receive_inbound_payload(
    db: Session,
    *,
    model_name: str,
    payload: dict[str, Any],
    endpoint: str,
    auth_context: AuthContext,
) -> dict[str, Any]:
    try:
        validate_identifier(model_name, "Data model name")
    except TableGenerationError as exc:
        raise InboundValidationError([{"field": "model_name", "message": str(exc)}]) from exc

    model = get_active_data_model_by_name(db, model_name)
    if model is None:
        raise LookupError("Data model not found")
    if model.type != "A":
        log_transaction(
            db,
            direction="inbound",
            protocol="rest",
            data_model_id=model.id,
            endpoint=endpoint,
            status="failed",
            request_payload=payload,
            error_message="Inbound API is only supported for Type A data models",
            auth_type=auth_context.auth_type,
            api_key_id=auth_context.api_key_id,
            user_id=auth_context.user_id,
            source_system=auth_context.source_system or model.source_system,
        )
        db.commit()
        raise ValueError("Inbound API is only supported for Type A data models")

    try:
        # TODO: Add upsert_by_key behavior in a later milestone.
        record_id = insert_inbound_record(db, model, payload)
        response_payload = {
            "status": "success",
            "model": model.name,
            "record_id": record_id,
            "message": "Data received successfully",
        }
        log_transaction(
            db,
            direction="inbound",
            protocol="rest",
            data_model_id=model.id,
            endpoint=endpoint,
            status="success",
            request_payload=payload,
            response_payload={
                **response_payload,
                "record_id": str(record_id),
            },
            auth_type=auth_context.auth_type,
            api_key_id=auth_context.api_key_id,
            user_id=auth_context.user_id,
            source_system=auth_context.source_system or model.source_system,
        )
        db.commit()
        return response_payload
    except InboundValidationError as exc:
        db.rollback()
        log_transaction(
            db,
            direction="inbound",
            protocol="rest",
            data_model_id=model.id,
            endpoint=endpoint,
            status="failed",
            request_payload=payload,
            error_message=json.dumps(exc.errors),
            auth_type=auth_context.auth_type,
            api_key_id=auth_context.api_key_id,
            user_id=auth_context.user_id,
            source_system=auth_context.source_system or model.source_system,
        )
        db.commit()
        raise
    except SQLAlchemyError as exc:
        db.rollback()
        message = f"Failed to insert inbound data: {exc.__class__.__name__}"
        log_transaction(
            db,
            direction="inbound",
            protocol="rest",
            data_model_id=model.id,
            endpoint=endpoint,
            status="failed",
            request_payload=payload,
            error_message=message,
            auth_type=auth_context.auth_type,
            api_key_id=auth_context.api_key_id,
            user_id=auth_context.user_id,
            source_system=auth_context.source_system or model.source_system,
        )
        db.commit()
        raise InboundInsertError(message) from exc

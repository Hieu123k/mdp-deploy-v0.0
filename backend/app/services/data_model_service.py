import uuid
from typing import Any

from pydantic import ValidationError
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models.data_model import DataModel
from app.models.transaction import Transaction
from app.schemas.data_model import DataModelCreate, DataModelUpdate
from app.services import table_generator
from app.services.table_generator import TableGenerationError
from app.services.type_b_mapping_service import (
    DEFAULT_RECENCY_COLUMN,
    LATEST_CONFIG_TYPE,
    _read_latest_config,
    validate_type_b_mapping,
)


def get_data_model(db: Session, data_model_id: uuid.UUID) -> DataModel | None:
    return db.get(DataModel, data_model_id)


def get_data_model_by_name(db: Session, name: str) -> DataModel | None:
    return db.scalar(select(DataModel).where(DataModel.name == name))


def list_data_models(
    db: Session,
    status: str | None = None,
    model_type: str | None = None,
    ai_enabled: bool | None = None,
    domain: str | None = None,
    source_layer: str | None = None,
    canonical_status: str | None = None,
    site_scope: str | None = None,
) -> list[DataModel]:
    query = select(DataModel).order_by(DataModel.created_at.desc())
    if status is not None:
        query = query.where(DataModel.status == status)
    if model_type is not None:
        query = query.where(DataModel.type == model_type)
    if ai_enabled is not None:
        query = query.where(DataModel.ai_enabled == ai_enabled)
    if domain is not None:
        query = query.where(DataModel.domain == domain)
    if source_layer is not None:
        query = query.where(DataModel.source_layer == source_layer)
    if canonical_status is not None:
        query = query.where(DataModel.canonical_status == canonical_status)
    if site_scope is not None:
        query = query.where(DataModel.site_scope == site_scope)
    return list(db.scalars(query))


def _attribute_payload(attributes: Any) -> list[dict[str, Any]]:
    return [
        attribute.model_dump(exclude_none=True)
        if hasattr(attribute, "model_dump")
        else dict(attribute)
        for attribute in attributes
    ]


def _payload_from_create(data_model_in: DataModelCreate) -> dict[str, Any]:
    payload = data_model_in.model_dump(exclude_none=True)
    payload["attributes"] = _attribute_payload(data_model_in.attributes)
    return payload


def _embed_latest_config(payload: dict[str, Any]) -> None:
    """Move the Type B dedup config (``latest_only``/``recency_column`` input fields) INTO the
    ``relationships`` JSON so it persists with no new DB column, then drop the input keys so they
    are never passed to the ORM constructor/setattr. Idempotent: any prior ``latest_config`` entry
    is replaced. When the toggle is off the entry is omitted - relationships stays exactly as it
    was before this feature (no behaviour change for existing models)."""
    latest_only = bool(payload.pop("latest_only", False))
    recency_column = payload.pop("recency_column", None)
    relationships = [
        relationship
        for relationship in (payload.get("relationships") or [])
        if not (isinstance(relationship, dict) and relationship.get("type") == LATEST_CONFIG_TYPE)
    ]
    if latest_only:
        # Persist the EFFECTIVE recency column (default updated_at) so the stored entry and
        # DataModelRead.recency_column match the column the dedup actually sorts by.
        entry: dict[str, Any] = {
            "type": LATEST_CONFIG_TYPE,
            "latest_only": True,
            "recency_column": recency_column or DEFAULT_RECENCY_COLUMN,
        }
        relationships.append(entry)
    payload["relationships"] = relationships or None


def _payload_from_model(data_model: DataModel) -> dict[str, Any]:
    return {
        "name": data_model.name,
        "display_name": data_model.display_name,
        "type": data_model.type,
        "category": data_model.category,
        "namespace": data_model.namespace,
        "domain": data_model.domain,
        "entity_type": data_model.entity_type,
        "business_process": data_model.business_process,
        "source_layer": data_model.source_layer,
        "canonical_status": data_model.canonical_status,
        "site_scope": data_model.site_scope,
        "description": data_model.description,
        "business_definition": data_model.business_definition,
        "owner_department": data_model.owner_department,
        "source_system": data_model.source_system,
        "primary_key": data_model.primary_key,
        "generated_table": data_model.generated_table,
        "attributes": data_model.attributes,
        "relationships": data_model.relationships,
        # Surface the persisted dedup config so a partial Edit that does not resend these fields
        # still preserves them through the merge below (instead of silently turning the toggle off).
        "latest_only": _read_latest_config(data_model.relationships)[0],
        "recency_column": _read_latest_config(data_model.relationships)[1],
        "refresh_policy": data_model.refresh_policy,
        "sensitivity_level": data_model.sensitivity_level,
        "ai_enabled": data_model.ai_enabled,
        "status": data_model.status,
    }


def validate_updated_data_model(
    data_model: DataModel,
    data_model_in: DataModelUpdate,
) -> dict[str, Any]:
    payload = _payload_from_model(data_model)
    update_data = data_model_in.model_dump(exclude_unset=True)
    payload.update(update_data)

    try:
        validated = DataModelCreate.model_validate(payload)
    except ValidationError:
        raise

    return _payload_from_create(validated)


def create_data_model(db: Session, data_model_in: DataModelCreate) -> DataModel:
    payload = _payload_from_create(data_model_in)

    try:
        if data_model_in.type == "A":
            generated_table = table_generator.get_generated_table_name(data_model_in.name)
            # If the generated table already exists it is an ORPHAN from a previously hard-deleted
            # model (data-safety keeps the table). REUSE it — CREATE TABLE IF NOT EXISTS makes the
            # create a no-op and the existing data survives. Model names are unique, so this can only
            # be an orphan, never a live-model collision.
            payload["generated_table"] = generated_table
        if data_model_in.type == "B":
            validate_type_b_mapping(db, data_model_in)
            payload["generated_table"] = None

        # Fold the dedup config into relationships and drop the input-only keys before the ORM
        # constructor (DataModel has no latest_only/recency_column column). No-op for Type A.
        _embed_latest_config(payload)
        data_model = DataModel(**payload)
        db.add(data_model)
        db.flush()

        if data_model.type == "A":
            table_generator.create_generated_table_for_model(db, data_model)

        db.commit()
        db.refresh(data_model)
        return data_model
    except Exception:
        db.rollback()
        raise


def update_data_model(
    db: Session,
    data_model: DataModel,
    data_model_in: DataModelUpdate,
) -> DataModel:
    update_payload = validate_updated_data_model(data_model, data_model_in)
    validated = DataModelCreate.model_validate(update_payload)
    if validated.type == "B":
        validate_type_b_mapping(db, validated)
    update_payload.pop("generated_table", None)
    # Fold the dedup config into relationships and drop the input-only keys (re-injecting replaces
    # any stale entry, so editing never accumulates duplicate latest_config entries).
    _embed_latest_config(update_payload)
    for field, value in update_payload.items():
        setattr(data_model, field, value)

    # Type A: keep the physical generated table in sync with the (possibly changed) attributes —
    # add any new columns so the model definition never silently diverges from the table and
    # inbound keeps working with the new attributes. Non-destructive (never drops columns).
    if data_model.type == "A":
        table_generator.sync_generated_table_columns(db, data_model)

    db.add(data_model)
    db.commit()
    db.refresh(data_model)
    return data_model


def deactivate_data_model(db: Session, data_model: DataModel) -> DataModel:
    # TODO: Define generated table archival/drop policy in a later milestone.
    data_model.status = "inactive"
    db.add(data_model)
    db.commit()
    db.refresh(data_model)
    return data_model


def delete_data_model_record(db: Session, data_model: DataModel) -> None:
    """Hard-delete ONLY the data-model metadata record (admin Delete action). DATA-SAFETY: this
    deliberately does NOT drop the generated ``mdp_data.dm_*`` table — the physical data survives
    and is reused if a model of the same name is re-created. Orphan-table cleanup is a later
    milestone.

    Transaction logs reference data_models.id (FK, RESTRICT). We KEEP those logs (audit/data-safety)
    but NULL their ``data_model_id`` first so the delete isn't blocked by the FK (and never 500s)."""
    db.execute(
        update(Transaction)
        .where(Transaction.data_model_id == data_model.id)
        .values(data_model_id=None)
    )
    db.delete(data_model)
    db.commit()

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_admin, require_permission
from app.db.session import get_db
from app.models.data_model import DataModel
from app.models.user import User
from app.schemas.data_model import (
    DataModelCreate,
    DataModelRead,
    DataModelUpdate,
    TypeBGenerateSqlRequest,
    TypeBParseSqlRequest,
)
from app.services.data_model_service import (
    create_data_model,
    deactivate_data_model,
    delete_data_model_record,
    get_data_model,
    get_data_model_by_name,
    list_data_models,
    update_data_model,
)
from app.services.table_generator import TableGenerationError
from app.services.type_b_mapping_service import (
    TypeBMappingError,
    preview_saved_type_b_model,
    preview_type_b_mapping,
    validate_type_b_mapping,
)
from app.services.type_b_sql_service import (
    TypeBSqlError,
    generate_type_b_sql,
    parse_type_b_sql,
)


router = APIRouter(
    prefix="/data-models",
    tags=["data-models"],
    dependencies=[Depends(get_current_user)],
)


def ensure_unique_name(
    db: Session,
    name: str | None,
    existing_id: uuid.UUID | None = None,
) -> None:
    if not name:
        return

    existing = get_data_model_by_name(db, name)
    if existing and existing.id != existing_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Data model name is already registered",
        )


@router.post(
    "",
    response_model=DataModelRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("data_model.create"))],
)
def create_data_model_endpoint(
    data_model_in: DataModelCreate,
    db: Annotated[Session, Depends(get_db)],
) -> DataModel:
    ensure_unique_name(db, data_model_in.name)
    try:
        return create_data_model(db, data_model_in)
    except TableGenerationError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except TypeBMappingError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=exc.errors,
        ) from exc


@router.get("", response_model=list[DataModelRead])
def list_data_models_endpoint(
    db: Annotated[Session, Depends(get_db)],
    status_filter: Annotated[str | None, Query(alias="status")] = None,
    type_filter: Annotated[str | None, Query(alias="type")] = None,
    ai_enabled: bool | None = None,
    domain: str | None = None,
    source_layer: str | None = None,
    canonical_status: str | None = None,
    site_scope: str | None = None,
) -> list[DataModel]:
    if type_filter is not None and type_filter not in {"A", "B"}:
        raise HTTPException(status_code=422, detail='type must be "A" or "B"')
    return list_data_models(
        db,
        status=status_filter,
        model_type=type_filter,
        ai_enabled=ai_enabled,
        domain=domain,
        source_layer=source_layer,
        canonical_status=canonical_status,
        site_scope=site_scope,
    )


@router.post("/type-b/validate-mapping")
def validate_type_b_mapping_endpoint(
    data_model_in: DataModelCreate,
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    try:
        return validate_type_b_mapping(db, data_model_in)
    except TypeBMappingError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=exc.errors,
        ) from exc


@router.post("/type-b/preview")
def preview_type_b_mapping_endpoint(
    data_model_in: DataModelCreate,
    db: Annotated[Session, Depends(get_db)],
    limit: Annotated[int, Query(ge=1)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict:
    try:
        return preview_type_b_mapping(db, data_model_in, limit=limit, offset=offset)
    except TypeBMappingError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=exc.errors,
        ) from exc


@router.post("/type-b/parse-sql")
def parse_type_b_sql_endpoint(
    body: TypeBParseSqlRequest,
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    # READ-ONLY: parses the SQL to an AST and maps it to the builder plan. NEVER executes the user's
    # SQL. (When a primary key is supplied it also runs the read-only Type B validator, which may issue
    # lightweight LIMIT-1/COUNT probes against the source tables for non-blocking warnings.)
    try:
        return parse_type_b_sql(
            db,
            body.sql,
            primary_key=body.primary_key,
            latest_only=body.latest_only,
            recency_column=body.recency_column,
        )
    except TypeBSqlError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=exc.errors,
        ) from exc


@router.post("/type-b/generate-sql")
def generate_type_b_sql_endpoint(
    body: TypeBGenerateSqlRequest,
) -> dict:
    # Pure plan -> SQL text rendering; no DB access, no execution.
    try:
        return generate_type_b_sql(
            base=body.base,
            attributes=body.attributes,
            relationships=body.relationships,
            primary_key=body.primary_key,
            latest_only=body.latest_only,
            recency_column=body.recency_column,
        )
    except TypeBSqlError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=exc.errors,
        ) from exc


@router.get("/{data_model_id}", response_model=DataModelRead)
def get_data_model_endpoint(
    data_model_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
) -> DataModel:
    data_model = get_data_model(db, data_model_id)
    if data_model is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Data model not found",
        )
    return data_model


@router.get("/{data_model_id}/mapped-preview")
def get_data_model_mapped_preview_endpoint(
    data_model_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
    limit: Annotated[int, Query(ge=1)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict:
    data_model = get_data_model(db, data_model_id)
    if data_model is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Data model not found",
        )
    try:
        return preview_saved_type_b_model(db, data_model, limit=limit, offset=offset)
    except TypeBMappingError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=exc.errors,
        ) from exc


@router.put(
    "/{data_model_id}",
    response_model=DataModelRead,
    dependencies=[Depends(require_permission("data_model.edit"))],
)
def update_data_model_endpoint(
    data_model_id: uuid.UUID,
    data_model_in: DataModelUpdate,
    db: Annotated[Session, Depends(get_db)],
) -> DataModel:
    data_model = get_data_model(db, data_model_id)
    if data_model is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Data model not found",
        )

    ensure_unique_name(db, data_model_in.name, existing_id=data_model.id)
    try:
        return update_data_model(db, data_model, data_model_in)
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=exc.errors(include_context=False),
        ) from exc
    except TypeBMappingError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=exc.errors,
        ) from exc


@router.delete(
    "/{data_model_id}",
    response_model=DataModelRead,
    dependencies=[Depends(require_permission("data_model.delete"))],
)
def deactivate_data_model_endpoint(
    data_model_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
) -> DataModel:
    data_model = get_data_model(db, data_model_id)
    if data_model is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Data model not found",
        )
    return deactivate_data_model(db, data_model)


@router.delete("/{data_model_id}/record", status_code=status.HTTP_204_NO_CONTENT)
def delete_data_model_endpoint(
    data_model_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
    _admin: Annotated[User, Depends(require_admin)],
) -> None:
    """Admin-only HARD delete of the model RECORD. DATA-SAFETY: the generated mdp_data.dm_* table
    is intentionally NOT dropped — physical data survives (reused if the model is re-created)."""
    data_model = get_data_model(db, data_model_id)
    if data_model is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Data model not found")
    delete_data_model_record(db, data_model)

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.data_model import (
    DataModelTemplateCreateModelRequest,
    DataModelTemplateCreateModelResponse,
    DataModelTemplateRead,
)
from app.services.data_model_service import create_data_model, get_data_model_by_name
from app.services.data_model_template_service import (
    data_model_from_template,
    get_data_model_template,
    list_data_model_templates,
)
from app.services.type_b_mapping_service import TypeBMappingError, validate_type_b_mapping


router = APIRouter(
    tags=["data-model-templates"],
    dependencies=[Depends(get_current_user)],
)


def require_template(template_key: str) -> DataModelTemplateRead:
    template = get_data_model_template(template_key)
    if template is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Data model template not found")
    return template


@router.get("/data-model-templates", response_model=list[DataModelTemplateRead])
def list_data_model_templates_endpoint() -> list[DataModelTemplateRead]:
    return list_data_model_templates()


@router.get("/data-model-templates/{template_key}", response_model=DataModelTemplateRead)
def get_data_model_template_endpoint(template_key: str) -> DataModelTemplateRead:
    return require_template(template_key)


@router.post(
    "/data-model-templates/{template_key}/create-model",
    response_model=DataModelTemplateCreateModelResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_model_from_template_endpoint(
    template_key: str,
    request: DataModelTemplateCreateModelRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> dict:
    _ = current_user
    template = require_template(template_key)
    data_model_in = data_model_from_template(
        template,
        name=request.name,
        display_name=request.display_name,
        source_schema=request.source_schema,
        source_table=request.source_table,
        status=request.status,
        overrides=request.overrides,
        config=request.config,
    )
    if get_data_model_by_name(db, data_model_in.name):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Data model name already exists",
        )
    try:
        validation = validate_type_b_mapping(db, data_model_in)
        data_model = create_data_model(db, data_model_in)
    except TypeBMappingError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=exc.errors,
        ) from exc

    return {
        "status": "success",
        "data_model": data_model,
        "warnings": validation.get("warnings") or [],
    }

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.migration import MigrationJob
from app.models.user import User
from app.schemas.migration import MigrationJobRead, MigrationTemplateCreateJobRequest, MigrationTemplateRead
from app.services.migration_service import create_migration_job, get_migration_job_by_name
from app.services.migration_template_service import (
    get_migration_template,
    list_migration_templates,
    migration_job_from_template,
)


router = APIRouter(
    tags=["migration-templates"],
    dependencies=[Depends(get_current_user)],
)


def require_template(template_key: str) -> MigrationTemplateRead:
    template = get_migration_template(template_key)
    if template is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Migration template not found")
    return template


@router.get("/migration-templates", response_model=list[MigrationTemplateRead])
def list_migration_templates_endpoint() -> list[MigrationTemplateRead]:
    return list_migration_templates()


@router.get("/migration-templates/{template_key}", response_model=MigrationTemplateRead)
def get_migration_template_endpoint(template_key: str) -> MigrationTemplateRead:
    return require_template(template_key)


@router.post(
    "/migration-templates/{template_key}/create-job",
    response_model=MigrationJobRead,
    status_code=status.HTTP_201_CREATED,
)
def create_job_from_template_endpoint(
    template_key: str,
    request: MigrationTemplateCreateJobRequest,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> MigrationJob:
    template = require_template(template_key)
    job_in = migration_job_from_template(
        template,
        name=request.name,
        source_connection_id=request.source_connection_id,
        source_schema=request.source_schema,
        target_table=request.target_table,
        estimated_rows=request.estimated_rows,
        estimated_size_gb=request.estimated_size_gb,
        config=request.config,
    )
    if get_migration_job_by_name(db, job_in.name):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Migration job name is already registered",
        )
    return create_migration_job(db, job_in, current_user.id)

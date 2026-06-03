import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.migration import MigrationJob, MigrationRun
from app.models.user import User
from app.schemas.migration import (
    MigrationJobCreate,
    MigrationJobRead,
    MigrationJobUpdate,
    MigrationRunCreate,
    MigrationRunRead,
    MigrationRunUpdate,
    TargetValidationResponse,
)
from app.services.migration_service import (
    create_migration_job,
    create_migration_run,
    deactivate_migration_job,
    get_migration_job,
    get_migration_job_by_name,
    get_migration_run,
    list_migration_jobs,
    list_migration_runs,
    update_migration_job,
    update_migration_run,
    validate_target_table,
)


router = APIRouter(
    tags=["migration-jobs"],
    dependencies=[Depends(get_current_user)],
)

ALLOWED_SOURCE_TYPES = {"oracle", "postgresql", "sqlserver", "external"}
ALLOWED_TOOLS = {"ora2pg", "manual", "external_tool", "native_small_table"}


def ensure_unique_name(
    db: Session,
    name: str | None,
    existing_id: uuid.UUID | None = None,
) -> None:
    if not name:
        return
    existing = get_migration_job_by_name(db, name)
    if existing and existing.id != existing_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Migration job name is already registered",
        )


def require_job(db: Session, job_id: uuid.UUID) -> MigrationJob:
    job = get_migration_job(db, job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Migration job not found")
    return job


def require_run(db: Session, run_id: uuid.UUID) -> MigrationRun:
    run = get_migration_run(db, run_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Migration run not found")
    return run


@router.post("/migration-jobs", response_model=MigrationJobRead, status_code=status.HTTP_201_CREATED)
def create_migration_job_endpoint(
    job_in: MigrationJobCreate,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> MigrationJob:
    ensure_unique_name(db, job_in.name)
    return create_migration_job(db, job_in, current_user.id)


@router.get("/migration-jobs", response_model=list[MigrationJobRead])
def list_migration_jobs_endpoint(
    db: Annotated[Session, Depends(get_db)],
    status_filter: Annotated[str | None, Query(alias="status")] = None,
    source_type: str | None = None,
    migration_tool: str | None = None,
) -> list[MigrationJob]:
    if source_type is not None and source_type not in ALLOWED_SOURCE_TYPES:
        raise HTTPException(status_code=422, detail="Invalid source_type")
    if migration_tool is not None and migration_tool not in ALLOWED_TOOLS:
        raise HTTPException(status_code=422, detail="Invalid migration_tool")
    return list_migration_jobs(
        db,
        status=status_filter,
        source_type=source_type,
        migration_tool=migration_tool,
    )


@router.get("/migration-jobs/{job_id}", response_model=MigrationJobRead)
def get_migration_job_endpoint(
    job_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
) -> MigrationJob:
    return require_job(db, job_id)


@router.put("/migration-jobs/{job_id}", response_model=MigrationJobRead)
def update_migration_job_endpoint(
    job_id: uuid.UUID,
    job_in: MigrationJobUpdate,
    db: Annotated[Session, Depends(get_db)],
) -> MigrationJob:
    job = require_job(db, job_id)
    ensure_unique_name(db, job_in.name, existing_id=job.id)
    return update_migration_job(db, job, job_in)


@router.delete("/migration-jobs/{job_id}", response_model=MigrationJobRead)
def deactivate_migration_job_endpoint(
    job_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
) -> MigrationJob:
    return deactivate_migration_job(db, require_job(db, job_id))


@router.post("/migration-jobs/{job_id}/runs", response_model=MigrationRunRead, status_code=status.HTTP_201_CREATED)
def create_migration_run_endpoint(
    job_id: uuid.UUID,
    run_in: MigrationRunCreate,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> MigrationRun:
    job = require_job(db, job_id)
    return create_migration_run(db, job, run_in, current_user.id)


@router.get("/migration-jobs/{job_id}/runs", response_model=list[MigrationRunRead])
def list_migration_runs_endpoint(
    job_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
) -> list[MigrationRun]:
    require_job(db, job_id)
    return list_migration_runs(db, job_id)


@router.get("/migration-runs/{run_id}", response_model=MigrationRunRead)
def get_migration_run_endpoint(
    run_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
) -> MigrationRun:
    return require_run(db, run_id)


@router.put("/migration-runs/{run_id}", response_model=MigrationRunRead)
def update_migration_run_endpoint(
    run_id: uuid.UUID,
    run_in: MigrationRunUpdate,
    db: Annotated[Session, Depends(get_db)],
) -> MigrationRun:
    return update_migration_run(db, require_run(db, run_id), run_in)


@router.post("/migration-runs/{run_id}/validate-target", response_model=TargetValidationResponse)
def validate_target_endpoint(
    run_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    return validate_target_table(db, require_run(db, run_id))

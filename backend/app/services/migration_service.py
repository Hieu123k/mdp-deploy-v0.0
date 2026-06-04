import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.models.migration import MigrationJob, MigrationRun, MigrationValidation
from app.schemas.migration import MigrationJobCreate, MigrationJobUpdate, MigrationRunCreate, MigrationRunUpdate
from app.services.db_browser_service import (
    DbBrowserNotFoundError,
    DbBrowserValidationError,
    list_columns,
    preview_table,
    schema_exists,
    table_exists,
    validate_identifier,
)
from app.services.table_generator import quote_identifier


class MigrationValidationError(Exception):
    pass


def get_migration_job(db: Session, job_id: uuid.UUID) -> MigrationJob | None:
    return db.get(MigrationJob, job_id)


def get_migration_run(db: Session, run_id: uuid.UUID) -> MigrationRun | None:
    return db.get(MigrationRun, run_id)


def get_migration_job_by_name(db: Session, name: str) -> MigrationJob | None:
    return db.scalar(select(MigrationJob).where(MigrationJob.name == name))


def _latest_run_subquery() -> Any:
    return (
        select(
            MigrationRun.migration_job_id,
            func.max(MigrationRun.created_at).label("latest_created_at"),
        )
        .group_by(MigrationRun.migration_job_id)
        .subquery()
    )


def list_migration_jobs(
    db: Session,
    *,
    status: str | None = None,
    source_type: str | None = None,
    migration_tool: str | None = None,
) -> list[MigrationJob]:
    query = select(MigrationJob).order_by(MigrationJob.created_at.desc())
    if status:
        query = query.where(MigrationJob.status == status)
    if source_type:
        query = query.where(MigrationJob.source_type == source_type)
    if migration_tool:
        query = query.where(MigrationJob.migration_tool == migration_tool)
    jobs = list(db.scalars(query))
    latest = _latest_by_job(db)
    for job in jobs:
        run = latest.get(job.id)
        job.latest_run_status = run.status if run else None  # type: ignore[attr-defined]
        job.latest_target_row_count = run.target_row_count if run else None  # type: ignore[attr-defined]
    return jobs


def _latest_by_job(db: Session) -> dict[uuid.UUID, MigrationRun]:
    runs = list(db.scalars(select(MigrationRun).order_by(MigrationRun.created_at.desc())))
    latest: dict[uuid.UUID, MigrationRun] = {}
    for run in runs:
        latest.setdefault(run.migration_job_id, run)
    return latest


def create_migration_job(
    db: Session,
    job_in: MigrationJobCreate,
    created_by: uuid.UUID | None,
) -> MigrationJob:
    job = MigrationJob(**job_in.model_dump(), created_by=created_by)
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def update_migration_job(
    db: Session,
    job: MigrationJob,
    job_in: MigrationJobUpdate,
) -> MigrationJob:
    for field, value in job_in.model_dump(exclude_unset=True).items():
        setattr(job, field, value)
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def deactivate_migration_job(db: Session, job: MigrationJob) -> MigrationJob:
    job.status = "inactive"
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def create_migration_run(
    db: Session,
    job: MigrationJob,
    run_in: MigrationRunCreate,
    triggered_by: uuid.UUID | None,
) -> MigrationRun:
    run = MigrationRun(
        migration_job_id=job.id,
        job=job,
        triggered_by=triggered_by,
        **run_in.model_dump(),
    )
    db.add(run)
    _apply_run_status_to_job(run)
    db.commit()
    db.refresh(run)
    return run


def update_migration_run(
    db: Session,
    run: MigrationRun,
    run_in: MigrationRunUpdate,
) -> MigrationRun:
    for field, value in run_in.model_dump(exclude_unset=True).items():
        setattr(run, field, value)
    _apply_run_status_to_job(run)
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def list_migration_runs(db: Session, job_id: uuid.UUID) -> list[MigrationRun]:
    return list(
        db.scalars(
            select(MigrationRun)
            .where(MigrationRun.migration_job_id == job_id)
            .order_by(MigrationRun.created_at.desc())
        )
    )


def _dialect_name(db: Session) -> str:
    return db.bind.dialect.name


def _qualified_table(db: Session, schema_name: str, table_name: str) -> str:
    if _dialect_name(db) == "postgresql":
        return f"{quote_identifier(schema_name)}.{quote_identifier(table_name)}"
    return quote_identifier(table_name)


def _count_rows(db: Session, schema_name: str, table_name: str) -> int:
    return int(
        db.execute(text(f"SELECT COUNT(*) FROM {_qualified_table(db, schema_name, table_name)}")).scalar_one()
    )


def _count_nulls(db: Session, schema_name: str, table_name: str, column_name: str) -> int:
    return int(
        db.execute(
            text(
                f"SELECT COUNT(*) FROM {_qualified_table(db, schema_name, table_name)} "
                f"WHERE {quote_identifier(column_name)} IS NULL"
            )
        ).scalar_one()
    )


def _count_duplicate_keys(
    db: Session,
    schema_name: str,
    table_name: str,
    primary_key_columns: list[str],
) -> int:
    key_expr = ", ".join(quote_identifier(column) for column in primary_key_columns)
    result = db.execute(
        text(
            "SELECT COUNT(*) FROM ("
            f"SELECT {key_expr}, COUNT(*) AS n "
            f"FROM {_qualified_table(db, schema_name, table_name)} "
            f"GROUP BY {key_expr} HAVING COUNT(*) > 1"
            ") duplicate_keys"
        )
    ).scalar_one()
    return int(result)


def _min_max_values(db: Session, schema_name: str, table_name: str, column_name: str) -> tuple[str | None, str | None]:
    row = db.execute(
        text(
            f"SELECT MIN({quote_identifier(column_name)}) AS min_value, "
            f"MAX({quote_identifier(column_name)}) AS max_value "
            f"FROM {_qualified_table(db, schema_name, table_name)}"
        )
    ).one()
    min_value = row[0]
    max_value = row[1]
    return (
        None if min_value is None else str(min_value),
        None if max_value is None else str(max_value),
    )


def _apply_run_status_to_job(run: MigrationRun) -> None:
    if run.status not in {"success", "failed"}:
        return
    now = datetime.now(timezone.utc)
    run.job.last_run_at = run.finished_at or now
    if run.status == "success":
        run.job.last_successful_run_at = run.finished_at or now
        if run.to_watermark:
            run.job.last_successful_watermark = run.to_watermark


def _validation_status(validations: list[MigrationValidation]) -> str:
    if not validations or any(validation.status == "fail" for validation in validations):
        return "fail"
    if any(validation.status == "warning" for validation in validations):
        return "warning"
    return "pass"


def _validation(
    run_id: uuid.UUID,
    check_name: str,
    *,
    status: str,
    target_value: str | None = None,
    source_value: str | None = None,
    message: str | None = None,
) -> MigrationValidation:
    return MigrationValidation(
        migration_run_id=run_id,
        check_name=check_name,
        source_value=source_value,
        target_value=target_value,
        status=status,
        message=message,
    )


def reconcile_ora2pg_run(
    db: Session, run: MigrationRun, *, source_rows: int | None = None
) -> dict[str, Any]:
    """Reconcile an ora2pg run: reuse ``validate_target_table`` to count the target and
    write ``MigrationValidation`` rows, then stamp a coarse ``validation_status`` of
    ``MATCH`` / ``MISMATCH`` / ``PENDING`` (source-vs-target row count). This is additive —
    it never touches ``run.status`` (the exit-0 lifecycle verdict), only the separate
    ``validation_status`` field. ``missed = source - target`` when both are known.
    """
    if source_rows is not None and run.source_row_count is None:
        run.source_row_count = source_rows
        db.add(run)
        db.flush()

    result = validate_target_table(db, run)  # writes validations + sets target_row_count

    match = result.get("row_count_match")
    status = "MATCH" if match is True else "MISMATCH" if match is False else "PENDING"
    missed = None
    if run.source_row_count is not None and result.get("target_row_count") is not None:
        missed = run.source_row_count - result["target_row_count"]

    run = db.get(MigrationRun, run.id)
    run.validation_status = status
    db.add(run)
    db.commit()
    db.refresh(run)
    return {
        "validation_status": status,
        "source_row_count": run.source_row_count,
        "target_row_count": result.get("target_row_count"),
        "missed": missed,
    }


def validate_target_table(db: Session, run: MigrationRun) -> dict[str, Any]:
    job = run.job
    target_schema = job.target_schema
    target_table = job.target_table
    primary_key_columns = job.primary_key_columns or []
    watermark_column = job.watermark_column

    validations: list[MigrationValidation] = []
    sample_rows: list[dict[str, Any]] = []
    target_row_count: int | None = None
    target_min_watermark: str | None = None
    target_max_watermark: str | None = None

    try:
        validate_identifier(target_schema, "target_schema")
        validate_identifier(target_table, "target_table")
        for column in primary_key_columns:
            validate_identifier(column, "primary_key_columns")
        if watermark_column:
            validate_identifier(watermark_column, "watermark_column")
    except DbBrowserValidationError as exc:
        validations.append(_validation(run.id, "identifier_validation", status="fail", message=str(exc)))
    else:
        if not schema_exists(db, target_schema):
            validations.append(
                _validation(run.id, "target_schema_exists", status="fail", message=f"Schema not found: {target_schema}")
            )
        elif not table_exists(db, target_schema, target_table):
            validations.append(
                _validation(run.id, "target_table_exists", status="fail", message=f"Table not found: {target_schema}.{target_table}")
            )
        else:
            validations.append(
                _validation(run.id, "target_table_exists", status="pass", target_value=f"{target_schema}.{target_table}")
            )
            columns = {column["column_name"] for column in list_columns(db, target_schema, target_table)}
            target_row_count = _count_rows(db, target_schema, target_table)
            validations.append(
                _validation(run.id, "target_row_count", status="pass", target_value=str(target_row_count))
            )
            if run.source_row_count is not None:
                row_counts_match = run.source_row_count == target_row_count
                validations.append(
                    _validation(
                        run.id,
                        "source_target_row_count",
                        status="pass" if row_counts_match else "fail",
                        source_value=str(run.source_row_count),
                        target_value=str(target_row_count),
                        message=None
                        if row_counts_match
                        else "Source row count does not match target row count from PostgreSQL validation",
                    )
                )
            for column in primary_key_columns:
                if column not in columns:
                    validations.append(
                        _validation(run.id, f"primary_key_column:{column}", status="fail", message="Primary key column not found")
                    )
                    continue
                null_count = _count_nulls(db, target_schema, target_table, column)
                validations.append(
                    _validation(
                        run.id,
                        f"primary_key_null_count:{column}",
                        status="pass" if null_count == 0 else "fail",
                        target_value=str(null_count),
                        message=None if null_count == 0 else "Primary key column contains null values",
                    )
                )
            if primary_key_columns and all(column in columns for column in primary_key_columns):
                duplicate_count = _count_duplicate_keys(db, target_schema, target_table, primary_key_columns)
                validations.append(
                    _validation(
                        run.id,
                        "primary_key_duplicate_count",
                        status="pass" if duplicate_count == 0 else "fail",
                        target_value=str(duplicate_count),
                        message=None if duplicate_count == 0 else "Duplicate primary key values found",
                    )
                )
            if watermark_column:
                if watermark_column not in columns:
                    validations.append(
                        _validation(
                            run.id,
                            f"watermark_column:{watermark_column}",
                            status="fail",
                            message="Watermark column not found in target table",
                        )
                    )
                else:
                    validations.append(
                        _validation(
                            run.id,
                            f"watermark_column:{watermark_column}",
                            status="pass",
                            target_value=watermark_column,
                        )
                    )
                    target_min_watermark, target_max_watermark = _min_max_values(
                        db,
                        target_schema,
                        target_table,
                        watermark_column,
                    )
                    validations.append(
                        _validation(
                            run.id,
                            "target_watermark_min",
                            status="pass" if target_min_watermark is not None else "warning",
                            target_value=target_min_watermark,
                            message=None if target_min_watermark is not None else "Target watermark minimum is null",
                        )
                    )
                    validations.append(
                        _validation(
                            run.id,
                            "target_watermark_max",
                            status="pass" if target_max_watermark is not None else "warning",
                            target_value=target_max_watermark,
                            message=None if target_max_watermark is not None else "Target watermark maximum is null",
                        )
                    )
            try:
                sample_rows = preview_table(db, target_schema, target_table, limit=10)["rows"]
            except (DbBrowserValidationError, DbBrowserNotFoundError):
                sample_rows = []

    db.query(MigrationValidation).filter(MigrationValidation.migration_run_id == run.id).delete()
    for validation in validations:
        db.add(validation)
    run.target_row_count = target_row_count
    run.target_min_watermark = target_min_watermark
    run.target_max_watermark = target_max_watermark
    run.validation_status = _validation_status(validations)
    db.add(run)
    db.commit()
    db.refresh(run)
    saved_validations = list(
        db.scalars(
            select(MigrationValidation)
            .where(MigrationValidation.migration_run_id == run.id)
            .order_by(MigrationValidation.created_at.asc(), MigrationValidation.check_name.asc())
        )
    )
    validation_status = _validation_status(saved_validations)
    status = "success" if validation_status in {"pass", "warning"} else "failed"
    row_count_match = None
    if run.source_row_count is not None and target_row_count is not None:
        row_count_match = run.source_row_count == target_row_count
    return {
        "status": status,
        "validation_status": validation_status,
        "migration_run_id": run.id,
        "target_schema": target_schema,
        "target_table": target_table,
        "source_row_count": run.source_row_count,
        "target_row_count": target_row_count,
        "row_count_match": row_count_match,
        "validations": saved_validations,
        "sample_rows": sample_rows,
    }

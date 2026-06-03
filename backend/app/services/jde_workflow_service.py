from typing import Any

from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.models.migration import MigrationJob, MigrationRun
from app.services.data_model_service import get_data_model_by_name
from app.services.db_browser_service import table_exists
from app.services.migration_service import get_migration_job_by_name
from app.services.procurement_staging_service import EXPECTED_TABLE_COUNTS, STAGING_SCHEMA


def _dialect_name(db: Session) -> str:
    return db.bind.dialect.name


def _qualified_table(db: Session, schema_name: str, table_name: str) -> str:
    if _dialect_name(db) == "postgresql":
        return f"{schema_name}.{table_name}"
    return table_name


def _safe_table_exists(db: Session, schema_name: str, table_name: str) -> bool:
    try:
        return table_exists(db, schema_name, table_name)
    except Exception:
        return False


def _safe_count(db: Session, schema_name: str, table_name: str) -> int:
    if not _safe_table_exists(db, schema_name, table_name):
        return 0
    try:
        return int(db.execute(text(f"SELECT COUNT(*) FROM {_qualified_table(db, schema_name, table_name)}")).scalar_one())
    except SQLAlchemyError:
        return 0


def _latest_run(db: Session, job: MigrationJob | None) -> MigrationRun | None:
    if job is None:
        return None
    return db.scalar(
        select(MigrationRun)
        .where(MigrationRun.migration_job_id == job.id)
        .order_by(MigrationRun.created_at.desc())
        .limit(1)
    )


def _model_ready(db: Session, model_name: str, source_schema: str, source_table: str) -> dict[str, Any]:
    model = get_data_model_by_name(db, model_name)
    exists = model is not None
    active = bool(model and model.status == "active")
    source_exists = _safe_table_exists(db, source_schema, source_table)
    return {
        "data_model_exists": exists,
        "data_model_id": str(model.id) if model else None,
        "data_model_status": model.status if model else None,
        "outbound_api_available": active and source_exists,
    }


def _migration_status(db: Session, job_name: str) -> dict[str, Any]:
    job = get_migration_job_by_name(db, job_name)
    run = _latest_run(db, job)
    return {
        "migration_job_exists": job is not None,
        "migration_job_id": str(job.id) if job else None,
        "migration_job_status": job.status if job else None,
        "latest_run_id": str(run.id) if run else None,
        "latest_run_status": run.status if run else None,
        "target_validation_status": run.validation_status if run else None,
        "target_row_count": run.target_row_count if run else None,
    }


def jde_procurement_workflow_status(db: Session) -> dict[str, Any]:
    table_counts = {
        table_name: _safe_count(db, STAGING_SCHEMA, table_name)
        for table_name in EXPECTED_TABLE_COUNTS
    }
    seeded = all(table_counts.get(table, 0) >= expected for table, expected in EXPECTED_TABLE_COUNTS.items())

    supplier = {
        **_migration_status(db, "migrate_jde_supplier_master"),
        **_model_ready(db, "supplier", STAGING_SCHEMA, "stg_jde_supplier"),
        "source_schema": STAGING_SCHEMA,
        "source_table": "stg_jde_supplier",
        "outbound_sample_key": "SUP-1001",
    }
    purchase_order_summary = {
        **_migration_status(db, "migrate_jde_purchase_order_summary_view"),
        **_model_ready(db, "purchase_order_summary", STAGING_SCHEMA, "vw_jde_purchase_order_summary"),
        "source_schema": STAGING_SCHEMA,
        "source_table": "vw_jde_purchase_order_summary",
        "outbound_sample_key": "PO-2026-0001",
    }

    return {
        "status": "success",
        "staging": {
            "procurement_staging_seeded": seeded,
            "tables": table_counts,
        },
        "supplier": supplier,
        "purchase_order_summary": purchase_order_summary,
    }

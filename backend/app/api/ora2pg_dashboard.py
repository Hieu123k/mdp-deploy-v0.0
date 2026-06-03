"""Migration Dashboard v0.0 — additive router that turns `migration-jobs` into a
real ora2pg control + monitoring dashboard.

All routes require auth (get_current_user), mounted alongside the existing
migration_jobs router. Nothing here modifies existing endpoints/behaviour.
"""
from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timezone
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.config import settings
from app.core.ora2pg_catalog import (
    MIGRATABLE_TABLES,
    build_ora2pg_conf,
    get_table,
    redact_conf,
)
from app.db.session import get_db
from app.models.migration import MigrationJob, MigrationRun
from app.models.user import User
from app.services.ora2pg_runner import get_progress, start_run

DASHBOARD_VERSION = "v0.0"

router = APIRouter(
    prefix="/ora2pg",
    tags=["ora2pg-dashboard"],
    dependencies=[Depends(get_current_user)],
)


def _job_name(target_table: str) -> str:
    return f"ora2pg_{target_table}"


def _get_or_create_job(db: Session, table) -> MigrationJob:
    name = _job_name(table.target_table)
    job = db.scalar(select(MigrationJob).where(MigrationJob.name == name))
    if job is not None:
        return job
    job = MigrationJob(
        name=name,
        description=f"ora2pg Oracle->mdp_staging migration for {table.table}",
        source_system="JDE Oracle",
        source_type="oracle",
        migration_tool="ora2pg",
        source_schema=settings.oracle_schema,
        source_table=table.table,
        target_schema=settings.ora2pg_target_schema,
        target_table=table.target_table,
        load_mode="full_load",
        watermark_column=table.ts_col,
        config={"dashboard": DASHBOARD_VERSION, "ts_col": table.ts_col},
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def _count_table(db: Session, target_table: str) -> int | None:
    try:
        return int(
            db.execute(
                text(
                    f'SELECT count(*) FROM "{settings.ora2pg_target_schema}"."{target_table}"'
                )
            ).scalar_one()
        )
    except Exception:
        return None


def _cursor_for(db: Session, target_table: str) -> str | None:
    """Best-effort read of the incremental cursor (dw_sync_schedules), if present."""
    for tbl in ("dw_sync_schedules", "inc_sync_schedules"):
        try:
            row = db.execute(
                text(
                    f"SELECT last_max_cursor FROM {tbl} WHERE pg_table = :t OR table_name = :t LIMIT 1"
                ),
                {"t": target_table},
            ).first()
            if row is not None:
                return None if row[0] is None else str(row[0])
        except Exception:
            continue
    return None


def _latest_run(db: Session, job_id: uuid.UUID) -> MigrationRun | None:
    return db.scalar(
        select(MigrationRun)
        .where(MigrationRun.migration_job_id == job_id)
        .order_by(MigrationRun.created_at.desc())
        .limit(1)
    )


def _run_snapshot(db: Session, run: MigrationRun) -> dict[str, Any]:
    """Merge live in-memory progress (if any) with the durable DB row."""
    live = get_progress(str(run.id))
    if live:
        return live
    elapsed = run.duration_seconds
    return {
        "run_id": str(run.id),
        "status": run.status,
        "phase": run.status,
        "rows_done": run.rows_loaded or 0,
        "rows_total": run.source_row_count,
        "pct": 100.0 if run.status == "success" else 0.0,
        "rows_per_sec": 0.0,
        "elapsed_sec": elapsed or 0,
        "eta_sec": 0 if run.status == "success" else None,
        "message": run.error_message or run.run_scope or run.status,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "updated_at": run.updated_at.isoformat() if run.updated_at else None,
    }


@router.get("/info")
def dashboard_info() -> dict[str, Any]:
    return {
        "version": DASHBOARD_VERSION,
        "ora2pg_container": settings.ora2pg_container,
        "target_schema": settings.ora2pg_target_schema,
        "oracle_configured": bool(settings.oracle_host and settings.oracle_user),
        "table_count": len(MIGRATABLE_TABLES),
    }


@router.get("/tables")
def list_tables(db: Annotated[Session, Depends(get_db)]) -> dict[str, Any]:
    items = []
    for t in MIGRATABLE_TABLES:
        job = db.scalar(select(MigrationJob).where(MigrationJob.name == _job_name(t.target_table)))
        last = _latest_run(db, job.id) if job else None
        items.append({
            "table": t.table,
            "ts_col": t.ts_col,
            "label": t.label,
            "target_table": t.target_table,
            "target_schema": settings.ora2pg_target_schema,
            "current_rows": _count_table(db, t.target_table),
            "cursor": _cursor_for(db, t.target_table),
            "last_run_id": str(last.id) if last else None,
            "last_run_status": last.status if last else None,
            "last_run_at": last.started_at.isoformat() if last and last.started_at else None,
        })
    return {"version": DASHBOARD_VERSION, "tables": items}


@router.get("/tables/{table_name}/config-preview")
def config_preview(table_name: str) -> dict[str, Any]:
    """Return the ora2pg.conf that would be generated (secrets redacted) — proves the
    config is built from env without exposing credentials and without running anything."""
    table = get_table(table_name)
    if table is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown table")
    return {
        "table": table.table,
        "target": f"{settings.ora2pg_target_schema}.{table.target_table}",
        "conf_redacted": redact_conf(build_ora2pg_conf(table)),
    }


@router.post("/tables/{table_name}/start", status_code=status.HTTP_202_ACCEPTED)
def start_migration(
    table_name: str,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    test_rows: int = 0,
) -> dict[str, Any]:
    table = get_table(table_name)
    if table is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown table")
    job = _get_or_create_job(db, table)

    # Refuse to start if a run for this job is already in flight (idempotent UX).
    existing = _latest_run(db, job.id)
    if existing and existing.status in {"pending", "running"}:
        live = get_progress(str(existing.id))
        if live and live.get("status") in {"pending", "running"}:
            return {"run_id": str(existing.id), "table": table.table, "status": existing.status,
                    "message": "A run is already in progress"}

    run = MigrationRun(
        migration_job_id=job.id,
        run_type="ora2pg_copy",
        trigger_type="dashboard",
        status="pending",
        started_at=datetime.now(timezone.utc),
        run_scope=f"ora2pg:{table.table}",
        triggered_by=current_user.id,
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    start_run(str(run.id), table, test_rows=test_rows)
    return {"run_id": str(run.id), "table": table.table, "status": "pending",
            "stream_url": f"/ora2pg/runs/{run.id}/stream"}


@router.get("/runs/{run_id}")
def get_run(run_id: uuid.UUID, db: Annotated[Session, Depends(get_db)]) -> dict[str, Any]:
    run = db.get(MigrationRun, run_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
    return _run_snapshot(db, run)


@router.get("/runs/{run_id}/stream")
async def stream_run(run_id: uuid.UUID, db: Annotated[Session, Depends(get_db)]) -> StreamingResponse:
    run = db.get(MigrationRun, run_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
    fallback = _run_snapshot(db, run)

    async def event_gen():
        last_payload: str | None = None
        # ~1h cap; the loop exits as soon as the run reaches a terminal state.
        for _ in range(3600):
            snap = get_progress(str(run_id)) or fallback
            payload = json.dumps(snap, default=str)
            if payload != last_payload:
                last_payload = payload
                yield f"data: {payload}\n\n"
            if snap.get("status") in {"success", "failed"}:
                break
            await asyncio.sleep(1)

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/status")
def db_status(db: Annotated[Session, Depends(get_db)]) -> dict[str, Any]:
    items = []
    for t in MIGRATABLE_TABLES:
        job = db.scalar(select(MigrationJob).where(MigrationJob.name == _job_name(t.target_table)))
        last = _latest_run(db, job.id) if job else None
        items.append({
            "table": t.table,
            "target": f"{settings.ora2pg_target_schema}.{t.target_table}",
            "current_rows": _count_table(db, t.target_table),
            "cursor": _cursor_for(db, t.target_table),
            "last_run_status": last.status if last else None,
            "last_run_rows": (last.rows_loaded if last else None),
            "last_run_at": last.started_at.isoformat() if last and last.started_at else None,
            "last_run_duration_sec": last.duration_seconds if last else None,
        })
    return {"version": DASHBOARD_VERSION, "schema": settings.ora2pg_target_schema, "tables": items}

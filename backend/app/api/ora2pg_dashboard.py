"""Migration Dashboard v0.0 — additive router that turns `migration-jobs` into a
real ora2pg control + monitoring dashboard.

All routes require auth (get_current_user), mounted alongside the existing
migration_jobs router. Nothing here modifies existing endpoints/behaviour.
"""
from __future__ import annotations

import asyncio
import csv
import io
import json
import uuid
from datetime import datetime, timezone
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel
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
from app.models.migration import MigrationJob, MigrationRun, MigrationValidation
from app.models.source_count import Ora2pgSourceCount
from app.models.user import User
from app.services.source_count_service import (
    get_all_source_counts,
    source_verdict,
    verify_exact,
)
from app.services.ora2pg_runner import (
    discover_oracle_keys,
    get_progress,
    start_repair,
    start_run,
)
from app.services.verify_service import enqueue_batch, get_batch_status, perform_verify

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
    # SAVEPOINT so a "relation does not exist" error rolls back only this probe and
    # does not abort the request transaction (postgres behaviour).
    try:
        with db.begin_nested():
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
            with db.begin_nested():
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


def _recon_fields(last: "MigrationRun | None") -> dict[str, Any]:
    """Reconciliation summary derived from a run (source vs target, missed, verdict, duration)."""
    if last is None:
        return {
            "last_source_rows": None, "last_target_rows": None, "last_missed": None,
            "last_validation_status": None, "last_run_duration_sec": None,
        }
    src, tgt = last.source_row_count, last.target_row_count
    missed = (src - tgt) if (src is not None and tgt is not None) else None
    return {
        "last_source_rows": src, "last_target_rows": tgt, "last_missed": missed,
        "last_validation_status": last.validation_status,
        "last_run_duration_sec": last.duration_seconds,
    }


def _source_count_fields(row: "Ora2pgSourceCount | None", current_rows: int | None) -> dict[str, Any]:
    """Source-count cache fields for a table (read from the cache — no Oracle call at load time).
    `source_verdict` is MATCH/MISMATCH only when the cached count is EXACT; an estimate yields
    ESTIMATE (not a red MISMATCH), nothing yields PENDING."""
    missed = None
    if row is not None and row.source_row_count is not None and current_rows is not None:
        missed = row.source_row_count - current_rows
    return {
        "source_count": row.source_row_count if row else None,
        "source_count_mode": row.count_mode if row else None,
        "source_count_at": row.counted_at.isoformat() if row and row.counted_at else None,
        "source_approximate": row.approximate if row else None,
        "source_stale": (row.status != "ok") if row else False,
        "source_missed": missed,
        "source_verdict": source_verdict(row, current_rows),
    }


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
    source_cache = get_all_source_counts(db)  # read cache once; NO Oracle call at load time
    for t in MIGRATABLE_TABLES:
        job = db.scalar(select(MigrationJob).where(MigrationJob.name == _job_name(t.target_table)))
        last = _latest_run(db, job.id) if job else None
        current_rows = _count_table(db, t.target_table)
        items.append({
            "table": t.table,
            "ts_col": t.ts_col,
            "label": t.label,
            "module": t.module,
            "target_table": t.target_table,
            "target_schema": settings.ora2pg_target_schema,
            "current_rows": current_rows,
            "cursor": _cursor_for(db, t.target_table),
            "last_run_id": str(last.id) if last else None,
            "last_run_status": last.status if last else None,
            "last_run_at": last.started_at.isoformat() if last and last.started_at else None,
            "pk_columns": job.primary_key_columns if job else None,
            **_recon_fields(last),
            **_source_count_fields(source_cache.get(t.table.upper()), current_rows),
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

    # Phase 2: if the PK has been discovered for this table, a UNIQUE index is created during
    # the load so later PK-repair (ON CONFLICT) works. Null pk → unchanged v0.0 behaviour.
    pk_columns = job.primary_key_columns or None
    start_run(str(run.id), table, test_rows=test_rows, pk_columns=pk_columns)
    return {"run_id": str(run.id), "table": table.table, "status": "pending",
            "stream_url": f"/ora2pg/runs/{run.id}/stream"}


@router.post("/tables/{table_name}/verify")
def verify_table(
    table_name: str,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> dict[str, Any]:
    """On-demand reconciliation: an EXACT COUNT(*) on the Oracle source view (cached) plus an
    exact COUNT of the target, giving an official MATCH/MISMATCH. The exact Oracle count runs
    only where Oracle is reachable (`.63`); on the VPS it degrades to `stale` and the verdict
    stays ESTIMATE/PENDING (never a fake MISMATCH)."""
    table = get_table(table_name)
    if table is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown table")
    return perform_verify(db, table)


class VerifyBatchRequest(BaseModel):
    tables: list[str]


@router.post("/verify-batch", status_code=status.HTTP_202_ACCEPTED)
def verify_batch(
    payload: VerifyBatchRequest,
    current_user: Annotated[User, Depends(get_current_user)],
) -> dict[str, Any]:
    """Queue many tables for exact-verify. Every table (single or batched) runs through ONE global
    worker that processes them **sequentially** — never two exact COUNTs at once. No cap on how
    many tables are selected; extras just wait their turn. Unknown tables are recorded as ``error``
    and the queue continues. Poll ``GET /ora2pg/verify-batch/{batch_id}`` for per-table status."""
    tables = [t for t in (payload.tables or []) if t and t.strip()]
    if not tables:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No tables selected")
    batch_id = enqueue_batch(tables)
    return {
        "batch_id": batch_id,
        "queued": tables,
        "status_url": f"/ora2pg/verify-batch/{batch_id}",
    }


@router.get("/verify-batch/{batch_id}")
def verify_batch_status(
    batch_id: str,
    current_user: Annotated[User, Depends(get_current_user)],
) -> dict[str, Any]:
    snap = get_batch_status(batch_id)
    if snap is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown batch")
    return snap


@router.post("/tables/{table_name}/repair", status_code=status.HTTP_202_ACCEPTED)
def repair_table(
    table_name: str,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
    mode: str | None = None,
    cutoff: str | None = None,
) -> dict[str, Any]:
    """Repair only the missing rows, without reloading the whole table.

    ``mode``:
    - ``pk`` (Phase 2, precise) — re-pull the source with ``INSERT … ON CONFLICT DO NOTHING``
      against the discovered PK; inserts exactly the missing rows, no duplicates. Needs the
      table's ``primary_key_columns`` (run discover-keys on `.63` first).
    - ``watermark`` (v0.0) — re-pull rows with ``ts_col >= cutoff`` (DELETE range then append).
    - ``full`` — full reload.
    When ``mode`` is omitted it auto-selects: pk → watermark → full, by what's available.
    """
    table = get_table(table_name)
    if table is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown table")
    if cutoff is not None and not str(cutoff).lstrip("-").isdigit():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="cutoff must be an integer")
    if mode is not None and mode not in {"pk", "watermark", "full"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="mode must be pk|watermark|full")

    job = _get_or_create_job(db, table)
    pk_columns = job.primary_key_columns or None

    # Resolve the effective mode (explicit request must be satisfiable, else 400).
    if mode == "pk" and not pk_columns:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail="No primary_key_columns for this table — run discover-keys (.63) or use mode=watermark")
    if mode == "watermark" and not (table.ts_col and cutoff is not None):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail="watermark repair needs ts_col + integer cutoff")
    if mode is None:
        effective = "pk" if pk_columns else "watermark" if (table.ts_col and cutoff is not None) else "full"
    else:
        effective = mode

    existing = _latest_run(db, job.id)
    if existing and existing.status in {"pending", "running"}:
        live = get_progress(str(existing.id))
        if live and live.get("status") in {"pending", "running"}:
            return {"run_id": str(existing.id), "table": table.table, "status": existing.status,
                    "message": "A run is already in progress"}

    run_type = {"pk": "ora2pg_repair_pk", "watermark": "ora2pg_repair", "full": "ora2pg_copy"}[effective]
    run = MigrationRun(
        migration_job_id=job.id,
        run_type=run_type,
        trigger_type="dashboard",
        status="pending",
        started_at=datetime.now(timezone.utc),
        run_scope=f"ora2pg-repair:{table.table}",
        triggered_by=current_user.id,
        from_watermark=str(cutoff) if effective == "watermark" else None,
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    if effective == "pk":
        start_repair(str(run.id), table, mode="pk", pk_columns=pk_columns)
    elif effective == "watermark":
        start_repair(str(run.id), table, mode="watermark", watermark_col=table.ts_col, cutoff=str(cutoff))
    else:
        start_run(str(run.id), table, pk_columns=pk_columns)  # full reload (keeps PK index if known)

    return {"run_id": str(run.id), "table": table.table, "mode": effective, "status": "pending",
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
            "module": t.module,
            "target": f"{settings.ora2pg_target_schema}.{t.target_table}",
            "current_rows": _count_table(db, t.target_table),
            "cursor": _cursor_for(db, t.target_table),
            "last_run_status": last.status if last else None,
            "last_run_rows": (last.rows_loaded if last else None),
            "last_run_at": last.started_at.isoformat() if last and last.started_at else None,
            **_recon_fields(last),
        })
    return {"version": DASHBOARD_VERSION, "schema": settings.ora2pg_target_schema, "tables": items}


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


def _csv_response(rows: list[dict[str, Any]], filename: str) -> Response:
    """Render rows (list of flat dicts) as a downloadable CSV. Empty list → header-less file."""
    buf = io.StringIO()
    if rows:
        writer = csv.DictWriter(buf, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    return Response(
        content=buf.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _run_report_row(run: MigrationRun) -> dict[str, Any]:
    job = run.job
    src, tgt = run.source_row_count, run.target_row_count
    missed = (src - tgt) if (src is not None and tgt is not None) else None
    return {
        "run_id": str(run.id),
        "source_table": job.source_table if job else None,
        "target": f"{job.target_schema}.{job.target_table}" if job else None,
        "run_type": run.run_type,
        "status": run.status,
        "validation_status": run.validation_status,
        "source_row_count": src,
        "target_row_count": tgt,
        "missed": missed,
        "duration_sec": run.duration_seconds,
        "started_at": _iso(run.started_at),
        "finished_at": _iso(run.finished_at),
        "repair_where": (
            f"{job.watermark_column} >= <cutoff>"
            if job and job.watermark_column
            else None
        ),
    }


@router.get("/runs/{run_id}/report")
def run_report(
    run_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
    format: str = "json",
) -> Any:
    """Downloadable reconciliation report for one run (source/target/missed/verdict/duration +
    the individual validation checks), built from migration_runs + migration_validations."""
    run = db.get(MigrationRun, run_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
    summary = _run_report_row(run)
    if format == "csv":
        return _csv_response([summary], f"reconciliation_run_{run_id}.csv")
    validations = db.scalars(
        select(MigrationValidation)
        .where(MigrationValidation.migration_run_id == run_id)
        .order_by(MigrationValidation.created_at.asc(), MigrationValidation.check_name.asc())
    ).all()
    return {
        **summary,
        "validations": [
            {
                "check_name": v.check_name,
                "status": v.status,
                "source_value": v.source_value,
                "target_value": v.target_value,
                "message": v.message,
            }
            for v in validations
        ],
    }


@router.get("/reconciliation")
def reconciliation_export(
    db: Annotated[Session, Depends(get_db)],
    format: str = "json",
) -> Any:
    """Reconciliation log across all catalog tables (latest run each) — JSON or CSV."""
    rows: list[dict[str, Any]] = []
    for t in MIGRATABLE_TABLES:
        job = db.scalar(select(MigrationJob).where(MigrationJob.name == _job_name(t.target_table)))
        last = _latest_run(db, job.id) if job else None
        src = last.source_row_count if last else None
        tgt = last.target_row_count if last else None
        missed = (src - tgt) if (src is not None and tgt is not None) else None
        rows.append({
            "table": t.table,
            "module": t.module,
            "target": f"{settings.ora2pg_target_schema}.{t.target_table}",
            "source_row_count": src,
            "target_row_count": tgt,
            "missed": missed,
            "validation_status": last.validation_status if last else None,
            "last_run_status": last.status if last else None,
            "duration_sec": last.duration_seconds if last else None,
            "started_at": _iso(last.started_at) if last else None,
            "finished_at": _iso(last.finished_at) if last else None,
            "run_id": str(last.id) if last else None,
            "repair_where": f"{t.ts_col} >= <cutoff>" if t.ts_col else None,
        })
    if format == "csv":
        return _csv_response(rows, "reconciliation.csv")
    return {"version": DASHBOARD_VERSION, "schema": settings.ora2pg_target_schema,
            "generated_from": "migration_runs + migration_validations", "tables": rows}


@router.get("/keys")
def list_keys(db: Annotated[Session, Depends(get_db)]) -> dict[str, Any]:
    """Current PK coverage per table (from MigrationJob.primary_key_columns). Drives which
    tables can use precise PK-repair vs the watermark/full-reload fallback."""
    items = []
    have = 0
    for t in MIGRATABLE_TABLES:
        job = db.scalar(select(MigrationJob).where(MigrationJob.name == _job_name(t.target_table)))
        pk = job.primary_key_columns if job else None
        if pk:
            have += 1
        items.append({
            "table": t.table, "module": t.module, "target_table": t.target_table,
            "pk_columns": pk, "repair_mode": "pk" if pk else ("watermark" if t.ts_col else "full"),
        })
    return {"version": DASHBOARD_VERSION, "with_pk": have, "total": len(MIGRATABLE_TABLES), "tables": items}


@router.post("/discover-keys")
def discover_keys(
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> dict[str, Any]:
    """Discover each table's PK from the Oracle unique index and persist it onto the table's
    MigrationJob.primary_key_columns. Needs Oracle → real only on `.63`; on the VPS it returns
    available=False (all pk null) without error, so the contract is still testable."""
    discovery = discover_oracle_keys(MIGRATABLE_TABLES)
    persisted = 0
    if discovery.get("available"):
        for r in discovery["results"]:
            if not r.get("pk_columns"):
                continue
            table = get_table(r["source_view"])
            if table is None:
                continue
            job = _get_or_create_job(db, table)
            job.primary_key_columns = r["pk_columns"]
            db.add(job)
            persisted += 1
        db.commit()
    return {
        "available": discovery.get("available", False),
        "message": discovery.get("message"),
        "persisted": persisted,
        "results": discovery.get("results", []),
    }

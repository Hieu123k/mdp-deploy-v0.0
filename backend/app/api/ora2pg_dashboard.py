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
import re
import uuid
from datetime import datetime, timezone
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_admin, require_permission
from app.core.config import settings
from app.core.ora2pg_catalog import (
    MIGRATABLE_TABLES,
    build_ora2pg_conf,
    get_table,
    redact_conf,
)
from app.db.session import engine, get_db
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
    # EXACT count — kept for Verify / validation, NOT for the tab-load path (see _estimate_table).
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


def _estimate_table(db: Session, target_table: str) -> int | None:
    """O(1) planner-stat estimate for the tab-load path (replaces a full count(*) per table).
    reltuples is -1 before the table's first ANALYZE/autovacuum and NULL when the relation is
    missing → both map to None ("?" / not-yet-known). Exact numbers come from Verify."""
    try:
        with db.begin_nested():
            val = db.execute(
                text(
                    "SELECT reltuples::bigint FROM pg_class "
                    "WHERE oid = to_regclass(:rel)"
                ),
                {"rel": f"{settings.ora2pg_target_schema}.{target_table}"},
            ).scalar()
        if val is None or val < 0:
            return None
        return int(val)
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
        # Finished/idle runs have NO ETA — return None so the UI shows "—", not a misleading "0".
        "eta_sec": None,
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


def _all_target_columns(db: Session) -> dict[str, set[str]]:
    """{target_table (lower): {columns (lower)}} for mdp_staging — one query, for PK warnings."""
    out: dict[str, set[str]] = {}
    try:
        rows = db.execute(
            text("SELECT table_name, column_name FROM information_schema.columns WHERE table_schema = :s"),
            {"s": settings.ora2pg_target_schema},
        ).fetchall()
        for tn, cn in rows:
            out.setdefault(str(tn).lower(), set()).add(str(cn).lower())
    except Exception:
        pass
    return out


def _pk_status(job: "MigrationJob | None", pk_columns, target_cols: set[str] | None) -> dict[str, Any]:
    """Resolve the PK source (reference|manual|scanned) + any warnings for the dashboard."""
    cfg = (job.config or {}) if job else {}
    source = cfg.get("pk_source") or ("reference" if pk_columns else None)
    warnings: list[str] = []
    # The pk_name_match / pk_type flags describe the REFERENCE-doc PK only. Once an admin has
    # overridden (manual) or a scan replaced it (scanned), those reference facts no longer describe
    # the live PK, so the warning would be stale/false — only surface them while source==reference.
    if source == "reference":
        if cfg.get("pk_name_match") is False:
            warnings.append("table name differs from JDE vanilla — verify PK applies")
        if cfg.get("pk_type") == "surrogate":
            warnings.append("PK is a surrogate key (UKID) — verify it suits upsert")
    if pk_columns and target_cols:  # only when the target is migrated
        missing = [c for c in pk_columns if c not in target_cols]
        if missing:
            warnings.append(f"PK column(s) not in view: {', '.join(missing)}")
    return {"pk_source": source, "pk_warning": "; ".join(warnings) if warnings else None}


@router.get("/tables")
def list_tables(db: Annotated[Session, Depends(get_db)]) -> dict[str, Any]:
    items = []
    source_cache = get_all_source_counts(db)  # read cache once; NO Oracle call at load time
    target_cols_map = _all_target_columns(db)  # one query for PK missing-column warnings
    for t in MIGRATABLE_TABLES:
        job = db.scalar(select(MigrationJob).where(MigrationJob.name == _job_name(t.target_table)))
        last = _latest_run(db, job.id) if job else None
        current_rows = _estimate_table(db, t.target_table)  # O(1) planner estimate (exact → Verify)
        pk = job.primary_key_columns if job else None
        items.append({
            "table": t.table,
            "ts_col": t.ts_col,
            "label": t.label,
            "module": t.module,
            "target_table": t.target_table,
            "target_schema": settings.ora2pg_target_schema,
            "current_rows": current_rows,
            "current_rows_estimated": True,
            "cursor": _cursor_for(db, t.target_table),
            "last_run_id": str(last.id) if last else None,
            "last_run_status": last.status if last else None,
            "last_run_at": last.started_at.isoformat() if last and last.started_at else None,
            "pk_columns": pk,
            **_pk_status(job, pk, target_cols_map.get(t.target_table.lower())),
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
    current_user: Annotated[User, Depends(require_permission("migration.run"))],
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
    current_user: Annotated[User, Depends(require_permission("migration.verify"))],
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
    current_user: Annotated[User, Depends(require_permission("migration.verify"))],
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
    current_user: Annotated[User, Depends(require_permission("migration.repair"))],
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
    current_user: Annotated[User, Depends(require_permission("pk.edit"))],  # consistent with set_primary_key
    table: str | None = None,
) -> dict[str, Any]:
    """Discover PK(s) from the Oracle unique index and persist onto MigrationJob.primary_key_columns
    (the canonical PK store) + sync into any streaming_config. ``table`` scans just that view (Scan
    PK per-table); omitted = scan all 40. Needs Oracle → real only where reachable; off-Oracle it
    returns available=False (all pk null) without error, so the contract is still testable.
    Admin-only (mutates the canonical + streaming PK), and never overrides a manual PK
    (manual > scanned > reference)."""
    if table is not None:
        one = get_table(table)
        if one is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown table")
        scan_list = [one]
    else:
        scan_list = MIGRATABLE_TABLES
    discovery = discover_oracle_keys(scan_list)
    persisted = 0
    skipped_manual = 0
    if discovery.get("available"):
        for r in discovery["results"]:
            if not r.get("pk_columns"):
                continue
            t = get_table(r["source_view"])
            if t is None:
                continue
            job = _get_or_create_job(db, t)
            if (job.config or {}).get("pk_source") == "manual":
                skipped_manual += 1  # manual always wins — a scan must never clobber it
                continue
            job.primary_key_columns = r["pk_columns"]
            job.config = {**(job.config or {}), "pk_source": "scanned"}
            db.add(job)
            _sync_streaming_pk(db, t.table, r["pk_columns"])
            persisted += 1
        db.commit()
    return {
        "available": discovery.get("available", False),
        "message": discovery.get("message"),
        "persisted": persisted,
        "skipped_manual": skipped_manual,
        "results": discovery.get("results", []),
    }


def _sync_streaming_pk(db: Session, source_view: str, pk_columns: list[str] | None) -> None:
    """Keep streaming_configs.primary_key_columns in sync with the canonical migration_jobs PK, so
    migrate (Repair upsert) and streaming (upsert) use ONE primary key. No-op where the streaming
    feature is absent (e.g. the standalone ui-bundle backend)."""
    try:
        from app.models.streaming_config import StreamingConfig

        cfg = db.scalar(select(StreamingConfig).where(StreamingConfig.source_view == source_view.upper()))
        if cfg is not None:
            cfg.primary_key_columns = pk_columns
            db.add(cfg)
    except Exception:  # streaming model not present / any error → canonical job PK still stands
        pass


def _target_columns(target_table: str) -> set[str]:
    """Lower-cased column names of the target staging table (for PK validation). Empty if missing."""
    try:
        with engine.connect() as conn:
            rows = conn.exec_driver_sql(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = %s AND table_name = %s",
                (settings.ora2pg_target_schema, target_table),
            ).fetchall()
        return {r[0].lower() for r in rows}
    except Exception:
        return set()


# Strict identifier allowlist for PK column names (defence against DDL injection — these names are
# interpolated into CREATE UNIQUE INDEX). PK columns are lower-cased first, so a-z/0-9/_ only.
_PK_COL_RE = re.compile(r"^[a-z][a-z0-9_]*$")


def _validate_pk_identifiers(pk_columns: list[str]) -> None:
    bad = [c for c in pk_columns if not _PK_COL_RE.fullmatch(c)]  # fullmatch: reject trailing-newline tricks
    if bad:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid column name(s): {', '.join(bad)} — use lower-case letters, digits, underscore",
        )


def _pk_has_duplicates(target_table: str, pk_columns: list[str]) -> bool:
    """True if the proposed PK is NOT unique in the migrated target (so a UNIQUE index would fail).
    Columns are pre-validated identifiers. Returns False if undeterminable (the index build is the
    final gate)."""
    schema = settings.ora2pg_target_schema
    cols = ", ".join(f'"{c}"' for c in pk_columns)
    try:
        with engine.connect() as conn:
            raw = conn.connection
            with raw.cursor() as cur:
                cur.execute(
                    f'SELECT 1 FROM "{schema}"."{target_table}" GROUP BY {cols} HAVING count(*) > 1 LIMIT 1'
                )
                return cur.fetchone() is not None
    except Exception:
        return False


def _rebuild_unique_index(target_table: str, pk_columns: list[str]) -> tuple[bool, str | None]:
    """Re-create the target's PK unique index on ``pk_columns`` ATOMICALLY: build a NEW unique index
    under a temp name first, and only if that succeeds drop the old + rename. So a non-unique PK
    (CREATE fails) leaves the prior index intact rather than the table index-less. Columns are
    pre-validated identifiers. Returns (ok, error)."""
    schema = settings.ora2pg_target_schema
    idx = f"ux_{target_table}_pk"[:63]
    tmp = f"ux_{target_table}_pk_new"[:63]
    cols = ", ".join(f'"{c}"' for c in pk_columns)
    try:
        with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
            raw = conn.connection
            with raw.cursor() as cur:
                cur.execute(f'DROP INDEX IF EXISTS "{schema}"."{tmp}"')
                cur.execute(f'CREATE UNIQUE INDEX "{tmp}" ON "{schema}"."{target_table}" ({cols})')
                cur.execute(f'DROP INDEX IF EXISTS "{schema}"."{idx}"')
                cur.execute(f'ALTER INDEX "{schema}"."{tmp}" RENAME TO "{idx}"')
        return True, None
    except Exception as exc:
        try:  # best-effort cleanup of the temp index; the prior ux_<t>_pk is untouched on failure
            with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
                with conn.connection.cursor() as cur:
                    cur.execute(f'DROP INDEX IF EXISTS "{schema}"."{tmp}"')
        except Exception:
            pass
        return False, str(exc).splitlines()[0][:300]


class PrimaryKeyUpdate(BaseModel):
    pk_columns: list[str]


@router.put("/tables/{table_name}/primary-key")
def set_primary_key(
    table_name: str,
    payload: PrimaryKeyUpdate,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_permission("pk.edit"))],
) -> dict[str, Any]:
    """Admin-only: set a table's primary key (single or composite) → canonical
    ``migration_jobs.primary_key_columns`` (synced to streaming_config) and rebuild the target's
    UNIQUE index. Validates the columns exist in the migrated target; a non-unique PK rebuilds with
    an error reported (not a crash)."""
    table = get_table(table_name)
    if table is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown table")
    pk = [c.strip().lower() for c in (payload.pk_columns or []) if c and c.strip()]
    if not pk:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="pk_columns must not be empty")
    # ALWAYS validate identifiers before they can be persisted or reach any DDL (no SQL injection).
    _validate_pk_identifiers(pk)

    target_cols = _target_columns(table.target_table)
    target_exists = bool(target_cols)
    if target_exists:
        unknown = [c for c in pk if c not in target_cols]
        if unknown:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Column(s) not in {table.target_table}: {', '.join(unknown)}",
            )
        # Reject a non-unique PK up-front (clear error, no crash) so we never persist a PK whose
        # UNIQUE index can't be built and never leave the table without an index.
        if _pk_has_duplicates(table.target_table, pk):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"PK {pk} is NOT unique in {table.target_table} — pick a unique key (single or composite).",
            )

    # Build the unique index FIRST when the target exists: the atomic CREATE UNIQUE INDEX is the
    # definitive uniqueness gate (the GROUP BY probe above can miss when it errors transiently). If
    # the build fails we persist NOTHING and return a hard 409 — so a non-unique PK never gets saved
    # as canonical and the contract "non-unique → non-2xx" holds even when the probe is undeterminable.
    index_rebuilt, index_error = (False, None)
    if target_exists:
        index_rebuilt, index_error = _rebuild_unique_index(table.target_table, pk)
        if not index_rebuilt:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"PK {pk} could not be made UNIQUE in {table.target_table}: {index_error}",
            )
    else:
        index_error = "target not migrated yet — index will be (re)built on next load/streaming cycle"

    # Persist canonical PK (pk_source=manual — overrides the reference default) + sync streaming.
    job = _get_or_create_job(db, table)
    job.primary_key_columns = pk
    job.config = {**(job.config or {}), "pk_source": "manual"}
    db.add(job)
    _sync_streaming_pk(db, table.table, pk)
    db.commit()

    return {
        "table": table.table,
        "pk_columns": pk,
        "index_rebuilt": index_rebuilt,
        "index_error": index_error,
        "message": "PK saved." + ("" if index_rebuilt else f" Index not unique-built: {index_error}"),
    }


@router.delete("/tables/{table_name}/primary-key")
def clear_primary_key(
    table_name: str,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(require_permission("pk.edit"))],
) -> dict[str, Any]:
    """Clear/Delete a table's primary key (admin/pk.edit): empties ``primary_key_columns`` + clears
    pk_source + DROPs the target's unique index ``ux_<target>_pk``. DATA-SAFETY: only the INDEX is
    dropped — the table and all rows are untouched. Consequence: with no PK the table can't upsert,
    so streaming falls back to Case B (full-reload)."""
    table = get_table(table_name)
    if table is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown table")

    # Drop ONLY the unique index (keep the data). Atomic-swap full-reloads keep this canonical name.
    idx = f"ux_{table.target_table}_pk"[:63]
    dropped = False
    try:
        with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
            conn.exec_driver_sql(f'DROP INDEX IF EXISTS "{settings.ora2pg_target_schema}"."{idx}"')
            dropped = True
    except Exception as exc:  # don't fail the clear just because the index couldn't be dropped
        logger_warn = str(exc)[:200]
    else:
        logger_warn = None

    job = _get_or_create_job(db, table)
    job.primary_key_columns = None
    cfg = dict(job.config or {})
    cfg.pop("pk_source", None)
    cfg.pop("pk_name_match", None)
    cfg.pop("pk_type", None)
    cfg.pop("pk_vanilla", None)
    job.config = cfg
    db.add(job)
    _sync_streaming_pk(db, table.table, None)  # streaming now has no PK → Case B full-reload
    db.commit()

    return {
        "table": table.table,
        "pk_columns": None,
        "index_dropped": dropped,
        "index_error": logger_warn,
        "message": f"PK cleared — unique index '{idx}' dropped (data kept). Streaming for this table now uses full-reload.",
    }

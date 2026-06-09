"""Multi-Verify — a single in-process queue + worker that runs exact-COUNT verifies SEQUENTIALLY.

The dashboard's per-row Verify (``verify_table``) is synchronous and does an exact Oracle
COUNT(*). Selecting many tables and verifying them at once must NOT fire many exact COUNTs in
parallel (that hammers Oracle). So every verify — single or batched — goes through ONE global
daemon worker: jobs are enqueued and processed one at a time, in order. A failed table (e.g. one
that does not exist) is recorded as ``error`` and the queue keeps going (never blocks the rest).

``perform_verify`` is the shared core, also used by the synchronous ``/verify`` endpoint, so the
two paths produce identical verdicts.
"""
from __future__ import annotations

import queue
import threading
import uuid
from collections import OrderedDict
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select, text

from app.core.config import settings
from app.core.ora2pg_catalog import Ora2pgTable, get_table
from app.db.session import SessionLocal
from app.models.migration import MigrationJob, MigrationRun, MigrationValidation
from app.services.source_count_service import source_verdict, verify_exact

# ---- shared verify core -------------------------------------------------------------------

def _job_name(target_table: str) -> str:
    return f"ora2pg_{target_table}"


def _latest_run(db: Any, job_id: Any) -> MigrationRun | None:
    return db.scalar(
        select(MigrationRun)
        .where(MigrationRun.migration_job_id == job_id)
        .order_by(MigrationRun.created_at.desc())
        .limit(1)
    )


def _count_target(db: Any, target_table: str) -> int | None:
    """Exact COUNT(*) of the target staging table; SAVEPOINT-guarded so a missing relation does
    not abort the surrounding transaction (postgres behaviour). Honours the configured target
    schema (``settings.ora2pg_target_schema``) like every other counter in the codebase."""
    try:
        with db.begin_nested():
            return int(
                db.execute(
                    text(f'SELECT count(*) FROM "{settings.ora2pg_target_schema}"."{target_table}"')
                ).scalar()
            )
    except Exception:
        return None


def perform_verify(db: Any, table: Ora2pgTable) -> dict[str, Any]:
    """Exact reconciliation for one table: exact target COUNT + exact Oracle source COUNT (cached)
    → official MATCH/MISMATCH. Records the verdict on the last run when official. Identical to the
    body of the synchronous ``/verify`` endpoint (shared so both paths agree)."""
    job = db.scalar(select(MigrationJob).where(MigrationJob.name == _job_name(table.target_table)))
    last = _latest_run(db, job.id) if job else None

    target_rows = _count_target(db, table.target_table)
    cache_row = verify_exact(db, table)
    verdict = source_verdict(cache_row, target_rows)
    src = cache_row.source_row_count if (cache_row and cache_row.status == "ok") else None
    missed = (src - target_rows) if (src is not None and target_rows is not None) else None

    if last is not None and verdict in {"MATCH", "MISMATCH"}:
        last.target_row_count = target_rows
        last.source_row_count = src
        last.validation_status = verdict
        db.add(last)
        db.add(MigrationValidation(
            migration_run_id=last.id,
            check_name="verify_target_row_count",
            source_value=str(src) if src is not None else None,
            target_value=str(target_rows) if target_rows is not None else None,
            status="pass" if verdict == "MATCH" else "fail",
            message=f"On-demand exact verify: target={target_rows}, source={src}, missed={missed}",
        ))
        db.commit()

    return {
        "table": table.table,
        "target_table": table.target_table,
        "target_rows": target_rows,
        "source_count": src,
        "source_count_mode": cache_row.count_mode if cache_row else None,
        "source_stale": (cache_row.status != "ok") if cache_row else True,
        "missed": missed,
        "source_verdict": verdict,
        "source_available": src is not None,
        "last_run_id": str(last.id) if last else None,
        "message": "Exact Oracle source count runs where Oracle is reachable; off-Oracle it stays ESTIMATE/stale.",
    }


# ---- global sequential queue --------------------------------------------------------------

_q: "queue.Queue[tuple[str, str]]" = queue.Queue()
_status: "OrderedDict[str, dict[str, Any]]" = OrderedDict()
_lock = threading.Lock()
_worker: threading.Thread | None = None
_MAX_BATCHES = 50  # keep the most recent N batches' status in memory


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _set_table(batch_id: str, name: str, **fields: Any) -> None:
    with _lock:
        batch = _status.get(batch_id)
        if batch is None:
            return
        row = batch["tables"].setdefault(name, {"status": "queued"})
        row.update(fields)
        row["updated_at"] = _now()


def _ensure_worker() -> None:
    global _worker
    with _lock:
        if _worker is not None and _worker.is_alive():
            return
        _worker = threading.Thread(target=_worker_loop, name="verify-queue", daemon=True)
        _worker.start()


def _worker_loop() -> None:
    while True:
        batch_id, name = _q.get()
        try:
            _set_table(batch_id, name, status="running")
            table = get_table(name)
            if table is None:
                _set_table(batch_id, name, status="error", error="unknown table")
            else:
                with SessionLocal() as db:
                    result = perform_verify(db, table)
                _set_table(
                    batch_id, name, status="done",
                    verdict=result.get("source_verdict"),
                    target_rows=result.get("target_rows"),
                    source_count=result.get("source_count"),
                    missed=result.get("missed"),
                )
        except Exception as exc:  # a single bad table must never stop the queue
            _set_table(batch_id, name, status="error", error=str(exc)[:500])
        finally:
            _q.task_done()


def enqueue_batch(table_names: list[str]) -> str:
    """Register a batch and enqueue each table for sequential verify. Duplicates within the batch
    are de-duplicated (order preserved). Returns the batch id."""
    seen: list[str] = []
    for n in table_names:
        if n and n not in seen:
            seen.append(n)
    batch_id = str(uuid.uuid4())
    with _lock:
        _status[batch_id] = {
            "batch_id": batch_id,
            "created_at": _now(),
            "order": seen,
            "tables": {n: {"status": "queued"} for n in seen},
        }
        # Evict only FINISHED batches (oldest first) — never drop status for in-flight work.
        if len(_status) > _MAX_BATCHES:
            for bid in list(_status.keys()):
                if len(_status) <= _MAX_BATCHES:
                    break
                b = _status[bid]
                done = sum(1 for v in b["tables"].values() if v.get("status") in {"done", "error"})
                if done >= len(b["order"]):
                    del _status[bid]
    _ensure_worker()
    for n in seen:
        _q.put((batch_id, n))
    return batch_id


def get_batch_status(batch_id: str) -> dict[str, Any] | None:
    with _lock:
        batch = _status.get(batch_id)
        if batch is None:
            return None
        # deep-ish copy for a stable snapshot
        snap = dict(batch)
        snap["tables"] = {k: dict(v) for k, v in batch["tables"].items()}
        done = sum(1 for v in batch["tables"].values() if v.get("status") in {"done", "error"})
        snap["total"] = len(batch["order"])
        snap["completed"] = done
        snap["finished"] = done >= len(batch["order"])
        return snap

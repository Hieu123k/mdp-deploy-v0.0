"""Migration Dashboard v0.0 — runs ora2pg for real against the `tipa_ora2pg`
container and streams live progress.

Isolation: this module is fully additive. It does not import or modify any of the
existing migration / data-model / connection / outbound logic. The `docker` SDK is
imported lazily (inside the worker) so the app and the full test-suite import cleanly
even where docker is unavailable.

Fail-graceful: when the configured Oracle host is unreachable — e.g. on the VPS sandbox —
ora2pg exits non-zero with a connection error; the worker captures it, marks the run
`failed` with a clear message, and never crashes the app. Real connect+execute is
only possible on `.63` (which can reach Oracle); the VPS only proves the wiring.
"""
from __future__ import annotations

import os
import re
import threading
import time
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text

from app.core.config import settings
from app.core.ora2pg_catalog import Ora2pgTable, build_ora2pg_conf, redact_conf
from app.db.session import SessionLocal, engine
from app.models.migration import MigrationRun

# run_id -> live progress snapshot. In-memory; the DB row is the durable fallback.
_PROGRESS: dict[str, dict[str, Any]] = {}
_LOCK = threading.Lock()

# ora2pg COPY progress line, e.g.
#   [=====>     ] 8500000/30475000 rows (27.9%) on total estimated data (82 sec, avg: 103000 recs/sec)
_PROGRESS_RE = re.compile(
    r"(\d+)\s*/\s*(\d+)\s+rows\s+\(([\d.]+)%\)(?:.*?avg:\s*(\d+)\s*recs/sec)?",
    re.IGNORECASE,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_progress(run_id: str) -> dict[str, Any] | None:
    with _LOCK:
        snap = _PROGRESS.get(run_id)
        return dict(snap) if snap else None


def _set(rid: str, **fields: Any) -> None:
    with _LOCK:
        snap = _PROGRESS.setdefault(rid, {})
        snap.update(fields)
        snap["updated_at"] = _now()


def _persist(run_id: str, **fields: Any) -> None:
    """Best-effort persist of progress/terminal state to the migration_runs row."""
    try:
        with SessionLocal() as db:
            run = db.get(MigrationRun, run_id)
            if run is None:
                return
            for key, value in fields.items():
                setattr(run, key, value)
            db.add(run)
            db.commit()
    except Exception:  # pragma: no cover - persistence must never crash the worker
        pass


def _exec_collect(client_api: Any, container_id: str, cmd: list[str]) -> tuple[int, str]:
    """Run a command in the ora2pg container, return (exit_code, combined_output)."""
    exec_id = client_api.exec_create(container_id, cmd=cmd, stdout=True, stderr=True)["Id"]
    out = client_api.exec_start(exec_id)
    text = out.decode("utf-8", errors="replace") if isinstance(out, (bytes, bytearray)) else str(out)
    code = client_api.exec_inspect(exec_id).get("ExitCode")
    return (code if code is not None else 1, text)


def _apply_ddl(schema: str, ddl_sql: str, target_table: str | None = None) -> None:
    """Create the target table in MDP's own postgres from ora2pg-generated DDL.

    Applies the DDL on a DEDICATED engine connection in AUTOCOMMIT mode (NOT the
    Session's in-transaction connection), so CREATE SCHEMA / CREATE TABLE actually
    persist instead of being rolled back when the Session closes (design 1B). psql
    meta lines (\\...) are stripped, like migrate.sh.

    If ``target_table`` is given, verifies with ``to_regclass`` that the table really
    exists afterwards and raises a clear error otherwise — so a downstream COPY never
    fails with a confusing ``relation ... does not exist``.
    """
    cleaned = "\n".join(l for l in ddl_sql.splitlines() if not l.lstrip().startswith("\\"))
    if not cleaned.strip():
        return
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        raw = conn.connection  # DBAPI connection in REAL autocommit (no surrounding tx)
        with raw.cursor() as cur:
            cur.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema}";')
            cur.execute(f'SET search_path TO "{schema}";')
            cur.execute(cleaned)  # psycopg3 runs the multi-statement auto_schema.sql
    if target_table is not None:
        with engine.connect() as conn:
            reg = conn.execute(
                text("SELECT to_regclass(:q)"), {"q": f'"{schema}"."{target_table}"'}
            ).scalar()
        if reg is None:
            raise RuntimeError(
                f"DDL applied but target table {schema}.{target_table} is missing"
            )


def _count_target(target_table: str) -> int | None:
    try:
        with SessionLocal() as db:
            raw = db.connection().connection
            with raw.cursor() as cur:
                cur.execute(
                    f'SELECT count(*) FROM "{settings.ora2pg_target_schema}"."{target_table}"'
                )
                return int(cur.fetchone()[0])
    except Exception:
        return None


def _ensure_audit_cols(schema: str, target: str, run_id: str) -> None:
    """Add per-row audit columns to the target staging table (idempotent), then point
    `_migrate_run_id`'s DEFAULT at this run. Must run AFTER `_apply_ddl` (which DROP/CREATEs
    the table from the Oracle structure) and BEFORE the COPY pass, so ora2pg's COPY — which
    lists only the source columns — lets these two columns take their DEFAULT for every row
    (verified on postgres: clock_timestamp() is evaluated per-row inside COPY).
    """
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        raw = conn.connection
        with raw.cursor() as cur:
            cur.execute(
                f'ALTER TABLE "{schema}"."{target}" '
                "ADD COLUMN IF NOT EXISTS _migrated_at timestamptz NOT NULL DEFAULT clock_timestamp()"
            )
            cur.execute(
                f'ALTER TABLE "{schema}"."{target}" ADD COLUMN IF NOT EXISTS _migrate_run_id uuid'
            )
            # run_id is our own MigrationRun UUID (never user input) — safe to inline.
            cur.execute(
                f'ALTER TABLE "{schema}"."{target}" '
                f"ALTER COLUMN _migrate_run_id SET DEFAULT '{run_id}'::uuid"
            )


def _reconcile(run_id: str, *, source_rows: int | None = None) -> None:
    """Best-effort reconciliation after a COPY: compare source vs target row count, write
    MigrationValidation rows and stamp validation_status. Never raises (must not crash the
    worker); the run's exit-0 `status` is left untouched."""
    try:
        from app.services.migration_service import reconcile_ora2pg_run

        with SessionLocal() as db:
            run = db.get(MigrationRun, run_id)
            if run is None:
                return
            reconcile_ora2pg_run(db, run, source_rows=source_rows)
    except Exception:  # pragma: no cover - reconciliation must never break the migration
        pass


def _open_ora2pg() -> tuple[Any, Any]:
    """Return (low-level docker api, ora2pg container). Raises if unreachable."""
    import docker  # lazy: only needed when a job actually runs

    client = docker.from_env()
    container = client.containers.get(settings.ora2pg_container)
    return client.api, container


def _write_conf(conf: str) -> None:
    os.makedirs(settings.ora2pg_shared_dir, exist_ok=True)
    with open(os.path.join(settings.ora2pg_shared_dir, "ora2pg.conf"), "w", encoding="utf-8") as fh:
        fh.write(conf)


def _copy_stream(api: Any, container_id: str, run_id: str, started: float, log_tail: list[str]) -> tuple[int | None, str | None]:
    """Run `ora2pg -t COPY`, stream stdout/stderr and parse progress into the live snapshot.
    Returns (exit_code, error). `error` is set only when the stream itself raised."""
    try:
        exec_id = api.exec_create(
            container_id,
            cmd=["ora2pg", "-c", "/config/ora2pg.conf", "-t", "COPY"],
            stdout=True, stderr=True,
        )["Id"]
        stream = api.exec_start(exec_id, stream=True)
        buf = ""
        last_db_write = 0.0
        for chunk in stream:
            buf += chunk.decode("utf-8", errors="replace") if isinstance(chunk, (bytes, bytearray)) else str(chunk)
            while "\n" in buf or "\r" in buf:
                idx = min((buf.index(c) for c in "\n\r" if c in buf))
                line, buf = buf[:idx], buf[idx + 1:]
                line = line.strip()
                if not line:
                    continue
                log_tail.append(line)
                if len(log_tail) > 400:
                    del log_tail[:200]
                m = _PROGRESS_RE.search(line)
                if m:
                    done = int(m.group(1))
                    total = int(m.group(2))
                    pct = float(m.group(3))
                    rps = float(m.group(4)) if m.group(4) else 0.0
                    elapsed = time.monotonic() - started
                    if not rps and elapsed > 0:
                        rps = done / elapsed
                    eta = (total - done) / rps if rps > 0 and total else None
                    _set(
                        run_id, status="running", phase="copy",
                        rows_done=done, rows_total=total, pct=pct,
                        rows_per_sec=round(rps, 1), elapsed_sec=round(elapsed, 1),
                        eta_sec=(round(eta, 1) if eta is not None else None),
                        message=line[-300:],
                    )
                    now = time.monotonic()
                    if now - last_db_write > 3:
                        last_db_write = now
                        _persist(run_id, rows_loaded=done, source_row_count=total)
        return api.exec_inspect(exec_id).get("ExitCode"), None
    except Exception as exc:
        return None, f"ora2pg COPY stream error: {exc}"


def _worker(run_id: str, table: Ora2pgTable, test_rows: int) -> None:
    started = time.monotonic()
    started_at = datetime.now(timezone.utc)
    _set(
        run_id,
        run_id=run_id,
        table=table.table,
        target_table=table.target_table,
        status="running",
        phase="starting",
        rows_done=0,
        rows_total=None,
        pct=0.0,
        rows_per_sec=0.0,
        elapsed_sec=0.0,
        eta_sec=None,
        message="Starting ora2pg…",
        started_at=started_at.isoformat(),
    )
    _persist(run_id, status="running", started_at=started_at, run_scope=f"ora2pg:{table.table}")

    log_tail: list[str] = []

    def fail(msg: str) -> None:
        elapsed = time.monotonic() - started
        _set(run_id, status="failed", phase="failed", message=msg[-500:], elapsed_sec=elapsed)
        _persist(
            run_id,
            status="failed",
            finished_at=datetime.now(timezone.utc),
            duration_seconds=int(elapsed),
            error_message=msg[-4000:],
            log_text="\n".join(log_tail)[-8000:] or None,
        )

    try:
        import docker  # lazy: only needed when a job actually runs
    except Exception as exc:  # pragma: no cover
        fail(f"docker SDK unavailable: {exc}")
        return

    # 1) Generate ora2pg.conf into the shared volume (== /config in the ora2pg container)
    try:
        conf = build_ora2pg_conf(table, test_rows=test_rows)
        os.makedirs(settings.ora2pg_shared_dir, exist_ok=True)
        conf_path = os.path.join(settings.ora2pg_shared_dir, "ora2pg.conf")
        with open(conf_path, "w", encoding="utf-8") as fh:
            fh.write(conf)
        # Log the config with secrets redacted (proves the conf is generated from env)
        log_tail.append("Generated /config/ora2pg.conf:\n" + redact_conf(conf))
        _set(run_id, phase="config", message="Generated ora2pg.conf (secrets redacted in log)")
    except Exception as exc:
        fail(f"Failed to generate ora2pg.conf: {exc}")
        return

    try:
        client = docker.from_env()
        container = client.containers.get(settings.ora2pg_container)
        api = client.api
    except Exception as exc:
        fail(f"Cannot reach ora2pg container '{settings.ora2pg_container}': {exc}")
        return

    # 2) DDL pass — ora2pg -t TABLE -> auto_schema.sql (this connects to Oracle; fails here on VPS)
    _set(run_id, phase="ddl", message="Extracting schema from Oracle (ora2pg -t TABLE)…")
    code, out = _exec_collect(
        api, container.id,
        ["ora2pg", "-c", "/config/ora2pg.conf", "-t", "TABLE", "-b", "/config", "-o", "auto_schema.sql"],
    )
    log_tail.append(out)
    if code != 0:
        fail(f"ora2pg TABLE (DDL) failed (exit {code}). Oracle reachable only on .63.\n{out}")
        return
    try:
        ddl_path = os.path.join(settings.ora2pg_shared_dir, "auto_schema.sql")
        ddl_sql = ""
        if os.path.exists(ddl_path):
            with open(ddl_path, encoding="utf-8") as fh:
                ddl_sql = fh.read()
        _apply_ddl(settings.ora2pg_target_schema, ddl_sql, target_table=table.target_table)
        # Per-row audit columns — added AFTER the DROP/CREATE DDL, BEFORE COPY (see _ensure_audit_cols).
        _ensure_audit_cols(settings.ora2pg_target_schema, table.target_table, run_id)
        _set(run_id, message="Target table ensured in mdp_staging (+ _migrated_at / _migrate_run_id)")
    except Exception as exc:
        fail(f"Failed to apply target DDL: {exc}")
        return

    # 3) COPY pass — stream rows and parse progress
    _set(run_id, phase="copy", message="Copying data (ora2pg -t COPY)…")
    exit_code, err = _copy_stream(api, container.id, run_id, started, log_tail)
    if err:
        fail(err)
        return

    elapsed = time.monotonic() - started
    if exit_code not in (0, None):
        fail(f"ora2pg COPY failed (exit {exit_code}).\n" + "\n".join(log_tail[-20:]))
        return

    # 4) Finalize — count target, mark success
    target_count = _count_target(table.target_table)
    snap = get_progress(run_id) or {}
    _set(
        run_id, status="success", phase="done",
        rows_done=target_count if target_count is not None else snap.get("rows_done", 0),
        pct=100.0, eta_sec=0, elapsed_sec=round(elapsed, 1),
        message=f"Done — {target_count} rows in mdp_staging.{table.target_table}",
    )
    _persist(
        run_id,
        status="success",
        finished_at=datetime.now(timezone.utc),
        duration_seconds=int(elapsed),
        rows_loaded=target_count,
        target_row_count=target_count,
        log_text="\n".join(log_tail)[-8000:] or None,
    )
    # 5) Reconciliation — source (ora2pg total) vs target → validation_status MATCH/MISMATCH.
    _reconcile(run_id, source_rows=snap.get("rows_total"))


def _repair_worker(run_id: str, table: Ora2pgTable, watermark_col: str, cutoff: str) -> None:
    """Repair-delta: re-pull only the watermark range ``watermark_col >= cutoff`` and append
    (no truncate, no DROP/CREATE). The target range is DELETEd first so a re-pull is idempotent
    without needing a unique constraint. Rows land with `_migrate_run_id` = this repair run."""
    started = time.monotonic()
    started_at = datetime.now(timezone.utc)
    _set(
        run_id, run_id=run_id, table=table.table, target_table=table.target_table,
        status="running", phase="starting", rows_done=0, rows_total=None, pct=0.0,
        rows_per_sec=0.0, elapsed_sec=0.0, eta_sec=None,
        message=f"Starting repair ({watermark_col} ≥ {cutoff})…", started_at=started_at.isoformat(),
    )
    _persist(run_id, status="running", started_at=started_at, run_scope=f"ora2pg-repair:{table.table}")
    log_tail: list[str] = []

    def fail(msg: str) -> None:
        elapsed = time.monotonic() - started
        _set(run_id, status="failed", phase="failed", message=msg[-500:], elapsed_sec=elapsed)
        _persist(
            run_id, status="failed", finished_at=datetime.now(timezone.utc),
            duration_seconds=int(elapsed), error_message=msg[-4000:],
            log_text="\n".join(log_tail)[-8000:] or None,
        )

    # Append + watermark filter. ora2pg WHERE targets the Oracle view column (upper-case);
    # the PG target column is lower-cased (PRESERVE_CASE 0).
    where = f"{table.table}[{watermark_col.upper()} >= {cutoff}]"
    try:
        conf = build_ora2pg_conf(table, truncate=False, where_clause=where)
        _write_conf(conf)
        log_tail.append("Generated /config/ora2pg.conf (repair):\n" + redact_conf(conf))
        _set(run_id, phase="config", message="Generated repair ora2pg.conf (append + WHERE)")
    except Exception as exc:
        fail(f"Failed to generate repair ora2pg.conf: {exc}")
        return

    try:
        api, container = _open_ora2pg()
    except Exception as exc:
        fail(f"Cannot reach ora2pg container '{settings.ora2pg_container}': {exc}")
        return

    # Make sure the audit columns exist and tag appended rows with this repair run.
    try:
        _ensure_audit_cols(settings.ora2pg_target_schema, table.target_table, run_id)
    except Exception as exc:
        fail(f"Failed to ensure audit columns: {exc}")
        return

    # Clear the target watermark range first (idempotent re-pull), then COPY-append.
    _set(run_id, phase="delete", message=f"Clearing target rows where {watermark_col} ≥ {cutoff}…")
    try:
        with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
            raw = conn.connection
            with raw.cursor() as cur:
                cur.execute(
                    f'DELETE FROM "{settings.ora2pg_target_schema}"."{table.target_table}" '
                    f'WHERE "{watermark_col.lower()}" >= %s',
                    (cutoff,),
                )
    except Exception as exc:
        fail(f"Failed to clear target range: {exc}")
        return

    _set(run_id, phase="copy", message=f"Re-pulling {watermark_col} ≥ {cutoff} (append)…")
    exit_code, err = _copy_stream(api, container.id, run_id, started, log_tail)
    if err:
        fail(err)
        return

    elapsed = time.monotonic() - started
    if exit_code not in (0, None):
        fail(f"ora2pg repair COPY failed (exit {exit_code}).\n" + "\n".join(log_tail[-20:]))
        return

    target_count = _count_target(table.target_table)
    snap = get_progress(run_id) or {}
    _set(
        run_id, status="success", phase="done",
        rows_done=target_count if target_count is not None else snap.get("rows_done", 0),
        pct=100.0, eta_sec=0, elapsed_sec=round(elapsed, 1),
        message=f"Repair done — {target_count} rows now in mdp_staging.{table.target_table}",
    )
    _persist(
        run_id, status="success", finished_at=datetime.now(timezone.utc),
        duration_seconds=int(elapsed), rows_loaded=target_count, target_row_count=target_count,
        log_text="\n".join(log_tail)[-8000:] or None,
    )
    _reconcile(run_id, source_rows=snap.get("rows_total"))


def start_run(run_id: str, table: Ora2pgTable, *, test_rows: int = 0) -> None:
    """Launch the ora2pg worker in a daemon thread (non-blocking)."""
    _set(run_id, run_id=run_id, table=table.table, status="pending", phase="queued",
         rows_done=0, rows_total=None, pct=0.0, message="Queued")
    thread = threading.Thread(target=_worker, args=(run_id, table, test_rows), daemon=True)
    thread.start()


def start_repair(run_id: str, table: Ora2pgTable, *, watermark_col: str, cutoff: str) -> None:
    """Launch the repair-delta worker in a daemon thread (non-blocking)."""
    _set(run_id, run_id=run_id, table=table.table, status="pending", phase="queued",
         rows_done=0, rows_total=None, pct=0.0, message="Queued (repair)")
    thread = threading.Thread(
        target=_repair_worker, args=(run_id, table, watermark_col, cutoff), daemon=True
    )
    thread.start()

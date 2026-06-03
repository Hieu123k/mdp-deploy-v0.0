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

from app.core.config import settings
from app.core.ora2pg_catalog import Ora2pgTable, build_ora2pg_conf, redact_conf
from app.db.session import SessionLocal
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


def _set(run_id: str, **fields: Any) -> None:
    with _LOCK:
        snap = _PROGRESS.setdefault(run_id, {})
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


def _apply_ddl(schema: str, ddl_sql: str) -> None:
    """Create the target table in MDP's own postgres from ora2pg-generated DDL.

    The backend already owns a connection to the target postgres, so it applies the
    schema directly (design 1B). psql meta lines (\\...) are stripped, like migrate.sh.
    """
    cleaned = "\n".join(l for l in ddl_sql.splitlines() if not l.lstrip().startswith("\\"))
    if not cleaned.strip():
        return
    with SessionLocal() as db:
        raw = db.connection().connection  # DBAPI connection
        prev_autocommit = raw.autocommit
        raw.autocommit = True
        try:
            with raw.cursor() as cur:
                cur.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema}";')
                cur.execute(f'SET search_path TO "{schema}";')
                cur.execute(cleaned)
        finally:
            raw.autocommit = prev_autocommit


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
        _apply_ddl(settings.ora2pg_target_schema, ddl_sql)
        _set(run_id, message="Target table ensured in mdp_staging")
    except Exception as exc:
        fail(f"Failed to apply target DDL: {exc}")
        return

    # 3) COPY pass — stream rows and parse progress
    _set(run_id, phase="copy", message="Copying data (ora2pg -t COPY)…")
    try:
        exec_id = api.exec_create(
            container.id,
            cmd=["ora2pg", "-c", "/config/ora2pg.conf", "-t", "COPY"],
            stdout=True, stderr=True,
        )["Id"]
        stream = api.exec_start(exec_id, stream=True)
        buf = ""
        last_db_write = 0.0
        for chunk in stream:
            buf += chunk.decode("utf-8", errors="replace") if isinstance(chunk, (bytes, bytearray)) else str(chunk)
            while "\n" in buf or "\r" in buf:
                idx = min(
                    (buf.index(c) for c in "\n\r" if c in buf),
                )
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
        exit_code = api.exec_inspect(exec_id).get("ExitCode")
    except Exception as exc:
        fail(f"ora2pg COPY stream error: {exc}")
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


def start_run(run_id: str, table: Ora2pgTable, *, test_rows: int = 0) -> None:
    """Launch the ora2pg worker in a daemon thread (non-blocking)."""
    _set(run_id, run_id=run_id, table=table.table, status="pending", phase="queued",
         rows_done=0, rows_total=None, pct=0.0, message="Queued")
    thread = threading.Thread(target=_worker, args=(run_id, table, test_rows), daemon=True)
    thread.start()

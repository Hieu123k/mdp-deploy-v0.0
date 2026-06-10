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
import shutil
import threading
import time
import uuid
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

# ora2pg COPY progress lines come in TWO shapes (both on STDERR), e.g.
#   [=====>     ] 8500000/30475000 rows (27.9%) on total estimated data (82 sec, avg: 103000 recs/sec)
#   [=====>     ] 250000/0 total rows (100.0%) - (3 sec., avg: 83333 recs/sec), V2_PRO_F0911 in progress.
# The 2nd shape is what we actually get when exporting a VIEW (ora2pg can't pre-count it, so the
# denominator is 0, the literal word "total" sits before "rows", and the % is a useless 100.0).
# The regex MUST tolerate the optional "total " and "tuples/sec" or live progress is dropped (the
# real cause of the "frozen until the end" bug — NOT stdout buffering; the lines arrive every ~3s).
_PROGRESS_RE = re.compile(
    r"(\d+)\s*/\s*(\d+)\s+(?:total\s+)?rows\s+\(([\d.]+)%\)(?:.*?avg:\s*(\d+)\s*(?:recs|tuples)/sec)?",
    re.IGNORECASE,
)

# Phase 2 PK discovery — a tiny Perl/DBI introspector run INSIDE the ora2pg container (which
# already has DBD::Oracle). Credentials arrive via the exec environment (never written to a
# file, never logged). Output is plain TSV lines: "IDX<tab>TABLE<tab>INDEX<tab>POS<tab>COL"
# for unique-index columns of the base JDE tables, and "COL<tab>VIEW<tab>COL" for the V2_PRO_
# view columns. No JSON module dependency (only DBI, which ora2pg guarantees).
_DISCOVER_PERL = r"""
use strict; use warnings; use DBI;
my $dbh = DBI->connect($ENV{ORA_DSN}, $ENV{ORA_USER}, $ENV{ORA_PWD},
                       { RaiseError => 1, AutoCommit => 1, PrintError => 0 });
my $tin = join(",", map { "'".$_."'" } split /,/, ($ENV{ORA_TABLES} // ""));
my $vin = join(",", map { "'".$_."'" } split /,/, ($ENV{ORA_VIEWS}  // ""));
if ($tin ne "") {
  my $s = $dbh->prepare(qq{
    SELECT i.table_name, i.index_name, c.column_position, c.column_name
    FROM all_indexes i JOIN all_ind_columns c
      ON c.index_name = i.index_name AND c.index_owner = i.owner
    WHERE i.uniqueness = 'UNIQUE' AND i.table_name IN ($tin)
    ORDER BY i.table_name, i.index_name, c.column_position });
  $s->execute();
  while (my @r = $s->fetchrow_array()) { print "IDX\t$r[0]\t$r[1]\t$r[2]\t$r[3]\n"; }
}
if ($vin ne "") {
  my $v = $dbh->prepare(qq{ SELECT table_name, column_name FROM all_tab_columns WHERE table_name IN ($vin) });
  $v->execute();
  while (my @r = $v->fetchrow_array()) { print "COL\t$r[0]\t$r[1]\n"; }
}
$dbh->disconnect();
"""


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


def _source_estimate(source_view: str) -> int | None:
    """Cached source row-count estimate (Ora2pgSourceCount) used to seed the live-progress
    denominator when ora2pg can't pre-count the view. Best-effort; None when not cached."""
    try:
        from app.models.source_count import Ora2pgSourceCount  # lazy: avoid import cycle
        from sqlalchemy import select

        with SessionLocal() as db:
            row = db.scalar(
                select(Ora2pgSourceCount).where(Ora2pgSourceCount.source_view == source_view.upper())
            )
            return int(row.source_row_count) if row and row.source_row_count else None
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


def _run_conf_paths(run_id: str) -> tuple[str, str]:
    """Per-run conf isolation (prompt 34): each ora2pg run gets its OWN dir so concurrent runs
    (streaming-loop + a manual migrate/verify) never overwrite each other's conf. Returns
    (backend_dir, container_dir): the same volume, seen as ``ora2pg_shared_dir`` by the backend and
    ``/config`` inside the ora2pg container."""
    sub = f"run_{run_id}"
    return os.path.join(settings.ora2pg_shared_dir, sub), f"/config/{sub}"


def _write_conf(conf: str, run_id: str) -> tuple[str, str]:
    """Write the per-run ora2pg.conf into its isolated dir. The conf carries Oracle credentials →
    stays in the (gitignored) volume only, chmod 600. Returns (backend_dir, container_dir)."""
    backend_dir, container_dir = _run_conf_paths(run_id)
    os.makedirs(backend_dir, exist_ok=True)
    path = os.path.join(backend_dir, "ora2pg.conf")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(conf)
    try:
        os.chmod(path, 0o600)
    except Exception:  # pragma: no cover - best effort on filesystems without chmod
        pass
    return backend_dir, container_dir


def _cleanup_run_conf(run_id: str) -> None:
    """Remove a run's conf dir (called after every run, success or fail) so per-run confs — and the
    streaming cycle that runs every few minutes — never pile up in the volume."""
    backend_dir, _ = _run_conf_paths(run_id)
    shutil.rmtree(backend_dir, ignore_errors=True)


def _worker_then_cleanup(worker: Any, run_id: str, *wargs: Any) -> None:
    """Thread target wrapper: run the worker, then ALWAYS drop its per-run conf dir."""
    try:
        worker(run_id, *wargs)
    finally:
        _cleanup_run_conf(run_id)


_PK_IDENT_RE = re.compile(r"^[a-z][a-z0-9_]*$")


def _index_columns(cur: Any, schema: str, index_name: str) -> tuple[list[str], bool]:
    """Return (ordered indexed column names, is_unique) for ``index_name`` in ``schema``; ([], False)
    when it doesn't exist. Used to reconcile an existing ux_<target>_pk against the wanted columns."""
    cur.execute(
        """
        SELECT a.attname, ix.indisunique
        FROM pg_class i
        JOIN pg_index ix ON ix.indexrelid = i.oid
        JOIN pg_class t ON t.oid = ix.indrelid
        JOIN pg_namespace n ON n.oid = t.relnamespace
        JOIN LATERAL unnest(ix.indkey) WITH ORDINALITY AS k(attnum, ord) ON TRUE
        JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = k.attnum
        WHERE n.nspname = %s AND i.relname = %s
        ORDER BY k.ord
        """,
        (schema, index_name),
    )
    rows = cur.fetchall()
    return [r[0] for r in rows], (bool(rows) and bool(rows[0][1]))


def _ensure_unique_index(schema: str, target: str, pk_columns: list[str]) -> None:
    """Ensure ``ux_<target>_pk`` is a UNIQUE index on EXACTLY ``pk_columns`` (lower-cased), reconciling
    COLUMNS — not just the index name. ``INSERT … ON CONFLICT DO NOTHING`` is emitted with NO explicit
    conflict target, so Postgres dedups against ANY unique index on the table: a STALE ux_<target>_pk
    left on different columns (e.g. after a sequence-marker swap) would silently dedup on the WRONG
    key and drop rows. We therefore DROP+rebuild when the columns differ. The rebuild is atomic (build
    a temp index, drop old, rename) so a NON-UNIQUE key fails the CREATE — raising a clear error to the
    caller's guard (streaming cycle / PK editor) and leaving the prior index intact. PK columns may
    come from the admin PK editor or a sequence marker used as the key, so every name is
    identifier-validated before any DDL (defence against injection)."""
    if not pk_columns:
        return
    cols_lower = [c.lower() for c in pk_columns]
    bad = [c for c in cols_lower if not _PK_IDENT_RE.fullmatch(c)]  # fullmatch: reject trailing-newline tricks
    if bad:
        raise ValueError(f"invalid PK column identifier(s): {', '.join(bad)}")
    cols = ", ".join(f'"{c}"' for c in cols_lower)
    idx = f"ux_{target}_pk"[:63]
    tmp = f"ux_{target}_pk_new"[:63]
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        raw = conn.connection
        with raw.cursor() as cur:
            existing, is_unique = _index_columns(cur, schema, idx)
            if existing == cols_lower and is_unique:
                return  # already the exact unique key — nothing to do
            if existing:
                # A stale/non-matching index owns the canonical name → atomic rebuild so the physical
                # index matches the current upsert key. A non-unique key fails the temp CREATE (raises).
                cur.execute(f'DROP INDEX IF EXISTS "{schema}"."{tmp}"')
                cur.execute(f'CREATE UNIQUE INDEX "{tmp}" ON "{schema}"."{target}" ({cols})')
                cur.execute(f'DROP INDEX IF EXISTS "{schema}"."{idx}"')
                cur.execute(f'ALTER INDEX "{schema}"."{tmp}" RENAME TO "{idx}"')
            else:
                # No index of this name → create it (a non-unique key raises here, as required).
                cur.execute(f'CREATE UNIQUE INDEX "{idx}" ON "{schema}"."{target}" ({cols})')


def _copy_stream(
    api: Any, container_id: str, run_id: str, started: float, log_tail: list[str], *,
    action: str = "COPY", total_hint: int | None = None, conf_path: str = "/config/ora2pg.conf",
) -> tuple[int | None, str | None]:
    """Run `ora2pg -t <action>` (COPY or INSERT), stream stdout/stderr and parse progress into
    the live snapshot. Returns (exit_code, error). `error` is set only when the stream raised.

    ``total_hint`` is an estimated source row-count (from the source-count cache) used as the
    denominator when ora2pg reports ``N/0 total rows`` (i.e. couldn't pre-count the view) so the
    UI still gets a real percentage + ETA. ``stdbuf -oL -eL`` is belt-and-suspenders line-buffering
    (the diagnosed freeze was a progress-regex mismatch, not buffering — but this guards larger
    exports and costs nothing when ora2pg already flushes)."""
    try:
        exec_id = api.exec_create(
            container_id,
            cmd=["stdbuf", "-oL", "-eL", "ora2pg", "-c", conf_path, "-t", action],
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
                    # ora2pg prints 0 as the denominator when it couldn't pre-count the view → fall
                    # back to the seeded source estimate so % and ETA are real, not a stuck 100%.
                    total = int(m.group(2)) or (total_hint or 0)
                    rps = float(m.group(4)) if m.group(4) else 0.0
                    elapsed = time.monotonic() - started
                    if not rps and elapsed > 0:
                        rps = done / elapsed
                    # Recompute % from the real total (ignore ora2pg's group-3 100% when total==0).
                    pct = round(min(100.0, 100.0 * done / total), 1) if total else 0.0
                    eta = (total - done) / rps if (rps > 0 and total and total > done) else None
                    _set(
                        run_id, status="running", phase="copy",
                        rows_done=done, rows_total=(total or None), pct=pct,
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
        return None, f"ora2pg {action} stream error: {exc}"


def _worker(run_id: str, table: Ora2pgTable, test_rows: int, pk_columns: list[str] | None = None) -> None:
    started = time.monotonic()
    started_at = datetime.now(timezone.utc)
    # Seed the live-progress denominator from the cached source estimate (so % + ETA work even
    # though ora2pg reports N/0 for a view). test_rows caps the run, so it wins as the total.
    total_hint = test_rows if test_rows and test_rows > 0 else _source_estimate(table.table)
    _set(
        run_id,
        run_id=run_id,
        table=table.table,
        target_table=table.target_table,
        status="running",
        phase="starting",
        rows_done=0,
        rows_total=total_hint,
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

    # 1) Generate this run's OWN ora2pg.conf into an isolated /config/run_<id>/ dir (no cross-run race)
    try:
        conf = build_ora2pg_conf(table, test_rows=test_rows)
        backend_dir, container_dir = _write_conf(conf, run_id)
        conf_arg = f"{container_dir}/ora2pg.conf"
        # Log the config with secrets redacted (proves the conf is generated from env)
        log_tail.append(f"Generated {conf_arg}:\n" + redact_conf(conf))
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
        ["ora2pg", "-c", conf_arg, "-t", "TABLE", "-b", container_dir, "-o", "auto_schema.sql"],
    )
    log_tail.append(out)
    if code != 0:
        fail(f"ora2pg TABLE (DDL) failed (exit {code}). Oracle reachable only on .63.\n{out}")
        return
    try:
        ddl_path = os.path.join(backend_dir, "auto_schema.sql")
        ddl_sql = ""
        if os.path.exists(ddl_path):
            with open(ddl_path, encoding="utf-8") as fh:
                ddl_sql = fh.read()
        _apply_ddl(settings.ora2pg_target_schema, ddl_sql, target_table=table.target_table)
        # Per-row audit columns — added AFTER the DROP/CREATE DDL, BEFORE COPY (see _ensure_audit_cols).
        _ensure_audit_cols(settings.ora2pg_target_schema, table.target_table, run_id)
        # Phase 2: a UNIQUE index on the PK enables later PK-repair (ON CONFLICT). Best-effort.
        if pk_columns:
            try:
                _ensure_unique_index(settings.ora2pg_target_schema, table.target_table, pk_columns)
            except Exception as exc:  # don't fail a load just because the PK index couldn't be made
                log_tail.append(f"warning: could not create unique PK index: {exc}")
        _set(run_id, message="Target table ensured in mdp_staging (+ _migrated_at / _migrate_run_id)")
    except Exception as exc:
        fail(f"Failed to apply target DDL: {exc}")
        return

    # 3) COPY pass — stream rows and parse progress
    _set(run_id, phase="copy", message="Copying data (ora2pg -t COPY)…")
    exit_code, err = _copy_stream(api, container.id, run_id, started, log_tail, total_hint=total_hint, conf_path=conf_arg)
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
        pct=100.0, eta_sec=None, elapsed_sec=round(elapsed, 1),  # done → no ETA (UI shows "—")
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
        _backend_dir, container_dir = _write_conf(conf, run_id)
        conf_arg = f"{container_dir}/ora2pg.conf"
        log_tail.append(f"Generated {conf_arg} (repair):\n" + redact_conf(conf))
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
    exit_code, err = _copy_stream(api, container.id, run_id, started, log_tail, conf_path=conf_arg)
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


def _repair_pk_worker(run_id: str, table: Ora2pgTable, pk_columns: list[str]) -> None:
    """PK-repair (Phase 2): re-pull the WHOLE source with `-t INSERT` + `INSERT_ON_CONFLICT
    DO NOTHING` against a UNIQUE index on the PK, so only the rows missing from the target are
    inserted — precise, no duplicates, no reload, existing rows untouched. Patched rows carry
    `_migrate_run_id` = this repair run."""
    started = time.monotonic()
    started_at = datetime.now(timezone.utc)
    _set(
        run_id, run_id=run_id, table=table.table, target_table=table.target_table,
        status="running", phase="starting", rows_done=0, rows_total=None, pct=0.0,
        rows_per_sec=0.0, elapsed_sec=0.0, eta_sec=None,
        message=f"Starting PK repair on ({', '.join(pk_columns)})…", started_at=started_at.isoformat(),
    )
    _persist(run_id, status="running", started_at=started_at, run_scope=f"ora2pg-repair-pk:{table.table}")
    log_tail: list[str] = []

    def fail(msg: str) -> None:
        elapsed = time.monotonic() - started
        _set(run_id, status="failed", phase="failed", message=msg[-500:], elapsed_sec=elapsed)
        _persist(
            run_id, status="failed", finished_at=datetime.now(timezone.utc),
            duration_seconds=int(elapsed), error_message=msg[-4000:],
            log_text="\n".join(log_tail)[-8000:] or None,
        )

    try:
        conf = build_ora2pg_conf(table, truncate=False, insert_on_conflict=True)
        _backend_dir, container_dir = _write_conf(conf, run_id)
        conf_arg = f"{container_dir}/ora2pg.conf"
        log_tail.append(f"Generated {conf_arg} (PK repair):\n" + redact_conf(conf))
        _set(run_id, phase="config", message="Generated PK-repair ora2pg.conf (INSERT ON CONFLICT)")
    except Exception as exc:
        fail(f"Failed to generate PK-repair ora2pg.conf: {exc}")
        return

    try:
        api, container = _open_ora2pg()
    except Exception as exc:
        fail(f"Cannot reach ora2pg container '{settings.ora2pg_container}': {exc}")
        return

    # Audit columns + the UNIQUE PK index that makes ON CONFLICT skip existing rows.
    try:
        _ensure_audit_cols(settings.ora2pg_target_schema, table.target_table, run_id)
        _ensure_unique_index(settings.ora2pg_target_schema, table.target_table, pk_columns)
    except Exception as exc:
        fail(f"Failed to prepare target for PK repair: {exc}")
        return

    _set(run_id, phase="copy", message="Re-pulling source (INSERT … ON CONFLICT DO NOTHING)…")
    exit_code, err = _copy_stream(api, container.id, run_id, started, log_tail, action="INSERT", conf_path=conf_arg)
    if err:
        fail(err)
        return

    elapsed = time.monotonic() - started
    if exit_code not in (0, None):
        fail(f"ora2pg PK-repair INSERT failed (exit {exit_code}).\n" + "\n".join(log_tail[-20:]))
        return

    target_count = _count_target(table.target_table)
    snap = get_progress(run_id) or {}
    _set(
        run_id, status="success", phase="done",
        rows_done=target_count if target_count is not None else snap.get("rows_done", 0),
        pct=100.0, eta_sec=0, elapsed_sec=round(elapsed, 1),
        message=f"PK repair done — {target_count} rows in mdp_staging.{table.target_table}",
    )
    _persist(
        run_id, status="success", finished_at=datetime.now(timezone.utc),
        duration_seconds=int(elapsed), rows_loaded=target_count, target_row_count=target_count,
        log_text="\n".join(log_tail)[-8000:] or None,
    )
    _reconcile(run_id, source_rows=snap.get("rows_total"))


def start_run(
    run_id: str, table: Ora2pgTable, *, test_rows: int = 0, pk_columns: list[str] | None = None
) -> None:
    """Launch the ora2pg worker in a daemon thread (non-blocking)."""
    _set(run_id, run_id=run_id, table=table.table, status="pending", phase="queued",
         rows_done=0, rows_total=None, pct=0.0, message="Queued")
    thread = threading.Thread(
        target=_worker_then_cleanup, args=(_worker, run_id, table, test_rows, pk_columns), daemon=True
    )
    thread.start()


def start_repair(
    run_id: str,
    table: Ora2pgTable,
    *,
    mode: str = "watermark",
    watermark_col: str | None = None,
    cutoff: str | None = None,
    pk_columns: list[str] | None = None,
) -> None:
    """Launch a repair worker. ``mode='pk'`` → PK repair (ON CONFLICT); otherwise the v0.0
    watermark-range repair (kept as fallback)."""
    _set(run_id, run_id=run_id, table=table.table, status="pending", phase="queued",
         rows_done=0, rows_total=None, pct=0.0, message="Queued (repair)")
    if mode == "pk" and pk_columns:
        thread = threading.Thread(
            target=_worker_then_cleanup, args=(_repair_pk_worker, run_id, table, pk_columns), daemon=True
        )
    else:
        thread = threading.Thread(
            target=_worker_then_cleanup, args=(_repair_worker, run_id, table, watermark_col, cutoff), daemon=True
        )
    thread.start()


def _drop_progress(run_id: str) -> None:
    with _LOCK:
        _PROGRESS.pop(run_id, None)


def target_exists(target_table: str) -> bool:
    """True if the target staging table exists (streaming requires an initial full load first)."""
    try:
        with engine.connect() as conn:
            reg = conn.execute(
                text("SELECT to_regclass(:q)"),
                {"q": f'"{settings.ora2pg_target_schema}"."{target_table}"'},
            ).scalar()
        return reg is not None
    except Exception:
        return False


def target_max_watermark(
    target_table: str, ts_col: str, ts_time_col: str | None = None, *, numeric: bool = False
) -> tuple[str | None, str | None]:
    """Return (max ``ts_col``, paired ``ts_time_col``) currently in the target staging table as
    strings. Used to (a) initialise the streaming cursor from the loaded baseline and (b) advance
    it after each pull. Returns (None, None) when the table is empty/unavailable. Column names are
    catalog/discovery values (never user input).

    ``numeric=True`` (sequence ids): the target columns are TEXT (MODIFY_TYPE *:text), so a plain
    MAX is LEXICOGRAPHIC ("99" > "200000") → the cursor would stall. Cast to numeric so MAX is
    arithmetic. (Julian CYYDDD is fixed-width 6 digits, so text-MAX already matches numeric there.)"""
    schema = settings.ora2pg_target_schema
    tcol = ts_col.lower()
    try:
        with SessionLocal() as db:
            raw = db.connection().connection
            with raw.cursor() as cur:
                if ts_time_col:
                    ttcol = ts_time_col.lower()
                    cur.execute(
                        f'SELECT "{tcol}", "{ttcol}" FROM "{schema}"."{target_table}" '
                        f'ORDER BY "{tcol}" DESC NULLS LAST, "{ttcol}" DESC NULLS LAST LIMIT 1'
                    )
                    row = cur.fetchone()
                    if not row or row[0] is None:
                        return None, None
                    return str(row[0]), (None if row[1] is None else str(row[1]))
                # Cast via ::text so this works whether ora2pg made the column NUMERIC or TEXT
                # (MODIFY_TYPE *:text vs DEFAULT_NUMERIC differ per table); numeric MAX, not lexical.
                expr = (
                    f'MAX(NULLIF("{tcol}"::text, \'\')::numeric)' if numeric else f'MAX("{tcol}")'
                )
                cur.execute(f'SELECT {expr} FROM "{schema}"."{target_table}"')
                row = cur.fetchone()
                if not row or row[0] is None:
                    return None, None
                # numeric → drop any trailing .0 so the cursor stays an integer-looking string
                val = row[0]
                if numeric:
                    val = int(val) if val == int(val) else val
                return str(val), None
    except Exception:
        return None, None


def streaming_pull_once(
    table: Ora2pgTable, *, where_clause: str, pk_columns: list[str]
) -> dict[str, Any]:
    """One streaming cycle: pull only the source rows matching ``where_clause`` (an ora2pg WHERE
    predicate on the view, e.g. ``V2_PRO_F0911[GLUPMJ >= 124001]``) and upsert them via ``-t
    INSERT`` + ``INSERT ON CONFLICT DO NOTHING`` against the target PK — so a re-pulled (``>=`` +
    lookback) row that already exists is skipped (idempotent, never duplicated).

    Synchronous; reuses the repair primitives (build_ora2pg_conf / _copy_stream / audit cols /
    unique index). The target table must already exist (do an initial full load first). Returns
    ``{ok, rows_before, rows_after, rows_added, exit_code, error, log}`` and never raises — a
    failed cycle must not kill the poll loop."""
    result: dict[str, Any] = {
        "ok": False, "rows_before": None, "rows_after": None, "rows_added": None,
        "exit_code": None, "error": None, "log": [],
    }
    if not target_exists(table.target_table):
        result["error"] = (
            f"target {settings.ora2pg_target_schema}.{table.target_table} does not exist — "
            "run an initial full load before streaming"
        )
        return result
    if not pk_columns:
        result["error"] = "no primary_key_columns — run discover-keys first (ON CONFLICT needs a unique key)"
        return result

    run_id = str(uuid.uuid4())
    log_tail: list[str] = []
    try:
        try:
            import docker  # noqa: F401  (lazy; surfaces a clear error if the SDK is missing)
        except Exception as exc:  # pragma: no cover
            result["error"] = f"docker SDK unavailable: {exc}"
            return result

        conf = build_ora2pg_conf(
            table, truncate=False, where_clause=where_clause, insert_on_conflict=True
        )
        _backend_dir, container_dir = _write_conf(conf, run_id)
        conf_arg = f"{container_dir}/ora2pg.conf"
        log_tail.append(f"Generated {conf_arg} (streaming):\n" + redact_conf(conf))

        try:
            api, container = _open_ora2pg()
        except Exception as exc:
            result["error"] = f"cannot reach ora2pg container '{settings.ora2pg_container}': {exc}"
            result["log"] = log_tail
            return result

        # Tag streamed rows with this cycle id, and (re)ensure the unique key index ON CONFLICT needs.
        # The key may be a real PK or a sequence marker used as the key (prompt 36); either way the
        # unique index must build — a non-unique key column fails HERE with a clear error (no crash,
        # no cursor advance, nothing persisted), which is exactly the "marker is not unique" signal.
        _ensure_audit_cols(settings.ora2pg_target_schema, table.target_table, run_id)
        try:
            _ensure_unique_index(settings.ora2pg_target_schema, table.target_table, pk_columns)
        except Exception as exc:
            result["error"] = (
                f"cannot build the unique upsert key on ({', '.join(pk_columns)}): {exc} — the key "
                "column(s) are not unique in the target (a sequence marker used as the key must be unique)"
            )
            result["log"] = log_tail[-40:]
            return result

        rows_before = _count_target(table.target_table)
        started = time.monotonic()
        exit_code, err = _copy_stream(api, container.id, run_id, started, log_tail, action="INSERT", conf_path=conf_arg)
        rows_after = _count_target(table.target_table)

        result.update(
            rows_before=rows_before, rows_after=rows_after, exit_code=exit_code, log=log_tail[-40:]
        )
        if rows_before is not None and rows_after is not None:
            result["rows_added"] = rows_after - rows_before
        if err:
            result["error"] = err
            return result
        if exit_code not in (0, None):
            result["error"] = f"ora2pg streaming INSERT failed (exit {exit_code})"
            return result
        result["ok"] = True
        return result
    except Exception as exc:  # pragma: no cover - the cycle must never crash the poll loop
        result["error"] = f"streaming cycle error: {exc}"
        result["log"] = log_tail[-40:]
        return result
    finally:
        _drop_progress(run_id)
        _cleanup_run_conf(run_id)  # never leave a streaming cycle's conf behind (runs every few min)


def _drop_table(schema: str, name: str) -> None:
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        conn.exec_driver_sql(f'DROP TABLE IF EXISTS "{schema}"."{name}"')


def _atomic_swap(schema: str, target: str, new_target: str, old_target: str, pk_columns: list[str] | None) -> None:
    """Swap <new_target> into place as <target> in ONE transaction so a reader NEVER sees an empty or
    missing target: RENAME target→_old, _new→target, (rename its unique index to the canonical name),
    DROP _old. ALTER … RENAME takes a brief ACCESS EXCLUSIVE lock; a concurrent SELECT either finishes
    on the old table or waits and then sees the new one — never nothing."""
    new_idx = f"ux_{new_target}_pk"[:63]
    canon_idx = f"ux_{target}_pk"[:63]
    with engine.begin() as conn:  # transactional (NOT autocommit) → all-or-nothing
        present = conn.exec_driver_sql(
            f"SELECT to_regclass('\"{schema}\".\"{target}\"')"
        ).scalar() is not None
        if present:
            conn.exec_driver_sql(f'ALTER TABLE "{schema}"."{target}" RENAME TO "{old_target}"')
        conn.exec_driver_sql(f'ALTER TABLE "{schema}"."{new_target}" RENAME TO "{target}"')
        # DROP _old BEFORE renaming the new index → frees the canonical index name ux_<target>_pk
        # (Postgres keeps the old table's index name on rename; index+table share a namespace, so
        # renaming into it while _old still exists would collide). Still atomic (one txn).
        if present:
            conn.exec_driver_sql(f'DROP TABLE "{schema}"."{old_target}"')
        if pk_columns:
            conn.exec_driver_sql(f'ALTER INDEX IF EXISTS "{schema}"."{new_idx}" RENAME TO "{canon_idx}"')


def full_reload_once(table: Ora2pgTable, *, pk_columns: list[str] | None = None) -> dict[str, Any]:
    """Case B (no watermark column): full re-copy of the view into ``<target>_new`` then an ATOMIC
    SWAP so the live target is NEVER empty for readers (Type B outbound). On ANY failure the live
    target is left untouched and ``<target>_new`` is dropped. Needs ~2× space transiently. Synchronous
    (runs in the streaming executor thread); never raises. Returns {ok, rows_before, rows_after,
    rows_added, exit_code, error, log}."""
    schema = settings.ora2pg_target_schema
    target = table.target_table
    new_target = f"{target}_new"
    old_target = f"{target}_old"
    run_id = str(uuid.uuid4())
    log_tail: list[str] = []
    result: dict[str, Any] = {
        "ok": False, "rows_before": None, "rows_after": None, "rows_added": None,
        "exit_code": None, "error": None, "log": [], "mode": "full",
    }
    try:
        result["rows_before"] = _count_target(target)  # None if first load (target absent)
        _drop_table(schema, new_target)  # clean any leftover temp from a prior crash
        _drop_table(schema, old_target)  # …and any stale _old left by a crashed swap

        conf = build_ora2pg_conf(table, truncate=True, replace_target=new_target)
        backend_dir, container_dir = _write_conf(conf, run_id)
        conf_arg = f"{container_dir}/ora2pg.conf"
        log_tail.append(f"Generated {conf_arg} (full-reload → {new_target}):\n" + redact_conf(conf))

        try:
            api, container = _open_ora2pg()
        except Exception as exc:
            result["error"] = f"cannot reach ora2pg container '{settings.ora2pg_container}': {exc}"
            result["log"] = log_tail
            return result

        # 1) DDL pass → create mdp_staging.<new_target>
        code, out = _exec_collect(
            api, container.id,
            ["ora2pg", "-c", conf_arg, "-t", "TABLE", "-b", container_dir, "-o", "auto_schema.sql"],
        )
        log_tail.append(out)
        if code != 0:
            _drop_table(schema, new_target)
            result["error"] = f"ora2pg TABLE (DDL) failed (exit {code}).\n{out[-400:]}"
            result["log"] = log_tail[-40:]
            return result
        ddl_path = os.path.join(backend_dir, "auto_schema.sql")
        ddl_sql = ""
        if os.path.exists(ddl_path):
            with open(ddl_path, encoding="utf-8") as fh:
                ddl_sql = fh.read()
        _apply_ddl(schema, ddl_sql, target_table=new_target)
        _ensure_audit_cols(schema, new_target, run_id)
        if pk_columns:
            try:
                _ensure_unique_index(schema, new_target, pk_columns)
            except Exception as exc:
                log_tail.append(f"warning: could not create unique PK index on {new_target}: {exc}")

        # 2) COPY pass → load <new_target> (truncate=True in conf)
        started = time.monotonic()
        exit_code, err = _copy_stream(api, container.id, run_id, started, log_tail, action="COPY", conf_path=conf_arg)
        result["exit_code"] = exit_code
        if err or exit_code not in (0, None):
            _drop_table(schema, new_target)  # live target untouched
            result["error"] = err or f"ora2pg full COPY failed (exit {exit_code})"
            result["log"] = log_tail[-40:]
            return result

        # 2b) NON-EMPTY GUARD: never publish an empty table over good data. A transient empty source
        # (ora2pg can exit 0 with 0 rows) must NOT wipe the live target — refuse the swap, keep old.
        new_count = _count_target(new_target)
        if (result["rows_before"] or 0) > 0 and (new_count or 0) == 0:
            _drop_table(schema, new_target)
            result["error"] = (
                f"refused full-reload swap: new copy is EMPTY ({new_count}) but live target has "
                f"{result['rows_before']} rows — keeping the live data (source likely transiently empty)"
            )
            result["log"] = log_tail[-40:]
            return result

        # 3) ATOMIC SWAP — live target never empty
        _atomic_swap(schema, target, new_target, old_target, pk_columns)
        result["rows_after"] = _count_target(target)
        rb, ra = result["rows_before"], result["rows_after"]
        result["rows_added"] = (ra - rb) if (rb is not None and ra is not None) else ra
        result["ok"] = True
        result["log"] = log_tail[-40:]
        return result
    except Exception as exc:  # pragma: no cover - a cycle must never crash the poll loop
        _drop_table(schema, new_target)  # never leave a half-built temp; live target untouched
        result["error"] = f"full-reload error: {exc}"
        result["log"] = log_tail[-40:]
        return result
    finally:
        _drop_progress(run_id)
        _cleanup_run_conf(run_id)


def _map_pk_to_view(index_cols: dict[str, list[tuple[int, str]]], view_cols: set[str]) -> tuple[list[str] | None, list[str]]:
    """Given a base table's unique indexes ({index_name: [(pos, COL)]}) and the V2_PRO_ view's
    columns, return (pk_columns_lowercased, unmapped). A column maps when the view exposes it
    by the same name, or by the name minus the 2-char JDE data-item prefix (e.g. GLDOC→DOC).
    Picks the fully-mappable unique index with the most columns; null if none maps cleanly."""
    best: list[str] | None = None
    last_unmapped: list[str] = []
    for cols in index_cols.values():
        ordered = [c for _, c in sorted(cols)]
        mapped: list[str] = []
        unmapped: list[str] = []
        for c in ordered:
            cu = c.upper()
            if cu in view_cols:
                mapped.append(cu.lower())
            elif len(cu) > 2 and cu[2:] in view_cols:
                mapped.append(cu[2:].lower())
            else:
                unmapped.append(c)
        if mapped and not unmapped:
            if best is None or len(mapped) > len(best):
                best = mapped
        else:
            last_unmapped = unmapped
    return best, ([] if best else last_unmapped)


def discover_oracle_keys(tables: list[Ora2pgTable]) -> dict[str, Any]:
    """Discover each table's PK from its Oracle UNIQUE index and map to the V2_PRO_ view columns.
    Runs the introspection inside the ora2pg container (needs Oracle → only real on `.63`).
    Returns {available, message, results:[{table_id, source_view, pk_columns, unmapped, error}]}.
    Never raises; on the VPS (no Oracle) returns available=False with all pk_columns=None."""
    base_to_view = {t.table.upper().replace("V2_PRO_", "", 1): t.table.upper() for t in tables}
    results = [
        {"table_id": b, "source_view": v, "pk_columns": None, "unmapped": [], "error": None}
        for b, v in base_to_view.items()
    ]
    by_id = {r["table_id"]: r for r in results}

    try:
        api, container = _open_ora2pg()
    except Exception as exc:
        for r in results:
            r["error"] = "ora2pg container unavailable"
        return {"available": False, "message": str(exc), "results": results}

    dsn = f"dbi:Oracle:host={settings.oracle_host};port={settings.oracle_port}"
    if settings.oracle_service_name:
        dsn += f";service_name={settings.oracle_service_name}"
    elif settings.oracle_sid:
        dsn += f";sid={settings.oracle_sid}"

    try:
        with open(os.path.join(settings.ora2pg_shared_dir, "discover_keys.pl"), "w", encoding="utf-8") as fh:
            fh.write(_DISCOVER_PERL)
        exec_id = api.exec_create(
            container.id,
            cmd=["perl", "/config/discover_keys.pl"],
            environment={
                "ORA_DSN": dsn,
                "ORA_USER": settings.oracle_user or "",
                "ORA_PWD": settings.oracle_pwd or "",
                "ORA_TABLES": ",".join(base_to_view.keys()),
                "ORA_VIEWS": ",".join(base_to_view.values()),
            },
            stdout=True, stderr=True,
        )["Id"]
        out = api.exec_start(exec_id)
        text_out = out.decode("utf-8", "replace") if isinstance(out, (bytes, bytearray)) else str(out)
        code = api.exec_inspect(exec_id).get("ExitCode")
    except Exception as exc:
        for r in results:
            r["error"] = "introspection exec failed"
        return {"available": False, "message": str(exc), "results": results}

    if "IDX\t" not in text_out and "COL\t" not in text_out:
        for r in results:
            r["error"] = "oracle unreachable / no rows"
        return {"available": False, "message": text_out.strip()[-300:] or f"exit {code}", "results": results}

    idx: dict[str, dict[str, list[tuple[int, str]]]] = {}
    viewcols: dict[str, set[str]] = {}
    for line in text_out.splitlines():
        p = line.split("\t")
        if p[0] == "IDX" and len(p) == 5:
            idx.setdefault(p[1].upper(), {}).setdefault(p[2], []).append((int(p[3]), p[4]))
        elif p[0] == "COL" and len(p) == 3:
            viewcols.setdefault(p[1].upper(), set()).add(p[2].upper())

    for b, v in base_to_view.items():
        r = by_id[b]
        pk, unmapped = _map_pk_to_view(idx.get(b, {}), viewcols.get(v, set()))
        r["pk_columns"] = pk
        r["unmapped"] = unmapped
        if pk is None and not idx.get(b):
            r["error"] = "no unique index found"
    return {"available": True, "message": "ok", "results": results}

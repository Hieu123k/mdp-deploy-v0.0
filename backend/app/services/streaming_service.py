"""Streaming (watermark-incremental) service — Migration Dashboard.

Detects rows that are new/changed in Oracle since the last cursor (via a JDE ``UPMJ`` Julian
update-date column) and upserts them into MDP's ``mdp_staging`` postgres using ora2pg
``INSERT … ON CONFLICT DO NOTHING`` (idempotent: a re-pulled row already present is skipped).

This module is fully additive. The predicate builder is a pure function (unit-tested without
Oracle); the cycle orchestration reuses the proven repair primitives in ``ora2pg_runner`` and the
``_exec_perl`` Oracle introspection from ``source_count_service``. All Oracle access is read-only
SELECT through the ora2pg container; no existing behaviour is modified.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.ora2pg_catalog import MIGRATABLE_TABLES, Ora2pgTable, get_table
from app.models.migration import MigrationJob
from app.models.streaming_config import StreamingConfig
from app.services import ora2pg_runner

logger = logging.getLogger("mdp.streaming")

GRANULARITIES = ("day", "timestamp")

# Tiny Perl/DBI probe (runs inside the ora2pg container, creds via exec env — never logged):
# list the columns a view exposes, so we can confirm a candidate time-of-day column (UPMT) exists
# before allowing ``granularity=timestamp``.
_PROBE_COLS_PERL = r"""
use strict; use warnings; use DBI;
my $dbh = DBI->connect($ENV{ORA_DSN}, $ENV{ORA_USER}, $ENV{ORA_PWD},
                       { RaiseError => 1, AutoCommit => 1, PrintError => 0 });
my $s = $dbh->prepare(qq{ SELECT column_name FROM all_tab_columns WHERE table_name = ? });
$s->execute($ENV{ORA_VIEW} // "");
while (my @r = $s->fetchrow_array()) { print "COL\t$r[0]\n"; }
$dbh->disconnect();
"""


def _as_int(value: Any, default: int | None) -> int | None:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def effective_granularity(granularity: str | None, ts_time_col: str | None) -> str:
    """``timestamp`` is only valid when a time-of-day column is configured; otherwise the table is
    locked to ``day`` (prod-safe default). Unknown values fall back to ``day``."""
    if granularity == "timestamp" and ts_time_col:
        return "timestamp"
    return "day"


def build_streaming_predicate(
    view: str,
    ts_col: str,
    *,
    ts_time_col: str | None = None,
    granularity: str = "day",
    cursor_day: str | None = None,
    cursor_time: str | None = None,
    lookback_days: int = 1,
    sequence: bool = False,
) -> str:
    """Build the ora2pg WHERE predicate for one streaming cycle: ``VIEW[<sql>]``.

    - ``sequence`` (monotonic id, e.g. ILUKID): ``ts_col > cursor`` — STRICT, NO lookback. An id is
      assign-once and never updated, so a re-pull would only duplicate; the cursor is ``MAX(id)``.
    - ``day``: ``ts_col >= (cursor_day - lookback_days)``. The ``>=`` + lookback re-pulls a small
      trailing window so same-day updates are not missed; ON CONFLICT then dedups. (JDE Julian
      ``CYYDDD`` arithmetic: plain integer subtraction; a year-boundary cutoff merely over-pulls a
      few rows, which is harmless because the upsert is idempotent.)
    - ``timestamp`` (only when ``ts_time_col`` is set): ``(ts_col > d) OR (ts_col = d AND
      ts_time_col >= t)`` — exact resume at a (day, time) cursor, no lookback needed.
    """
    view_u = view.upper()
    col = ts_col.upper()
    if sequence:
        c = _as_int(cursor_day, 0)
        return f"{view_u}[{col} > {c}]"
    gran = effective_granularity(granularity, ts_time_col)
    if gran == "timestamp":
        tcol = (ts_time_col or "").upper()
        d = _as_int(cursor_day, 0)
        t = _as_int(cursor_time, 0)
        return f"{view_u}[({col} > {d}) OR ({col} = {d} AND {tcol} >= {t})]"
    d = _as_int(cursor_day, None)
    if d is None:
        cutoff: Any = cursor_day if cursor_day not in (None, "") else 0
    else:
        cutoff = d - max(0, int(lookback_days or 0))
    return f"{view_u}[{col} >= {cutoff}]"


# --- config CRUD -----------------------------------------------------------------------------

def get_config(db: Session, source_view: str) -> StreamingConfig | None:
    return db.scalar(select(StreamingConfig).where(StreamingConfig.source_view == source_view.upper()))


def list_configs(db: Session) -> dict[str, StreamingConfig]:
    rows = db.scalars(select(StreamingConfig)).all()
    return {r.source_view.upper(): r for r in rows}


def _default_ts_col(table: Ora2pgTable) -> str | None:
    """Catalog ts_col is the JDE data-item (e.g. ``upmj``); the physical view column carries the
    2-char table prefix (e.g. ``GLUPMJ``). We can only HINT here — the operator sets the exact
    view column via PUT (verified per environment, since prod views may de-prefix)."""
    return table.ts_col.upper() if table.ts_col else None


def upsert_config(db: Session, source_view: str, **fields: Any) -> StreamingConfig:
    table = get_table(source_view)
    cfg = get_config(db, source_view)
    if cfg is None:
        cfg = StreamingConfig(
            source_view=source_view.upper(),
            target_table=table.target_table if table else source_view.lower(),
            ts_col=None,  # admin picks the watermark column explicitly (or "(none)" → full-reload)
        )
        db.add(cfg)
    for key, value in fields.items():
        if value is not None and hasattr(cfg, key):
            setattr(cfg, key, value)
    db.commit()
    db.refresh(cfg)
    return cfg


def config_view(
    cfg: StreamingConfig | None, table: Ora2pgTable, *, pk: list[str] | None = None
) -> dict[str, Any]:
    """Serialise a config (saved row or catalog default) for the API.

    ``pk`` overrides the canonical PK (from migration_jobs) so the Streaming tab shows the same PK
    the upsert actually uses; falls back to the config's own copy when not supplied."""
    # Authoritative: a saved row's ts_col IS the choice (None/"" → full-reload). The catalog hint is
    # only a suggestion when no row exists yet.
    ts_col = ((cfg.ts_col or "").strip() or None) if cfg else _default_ts_col(table)
    gran = effective_granularity(cfg.granularity if cfg else "day", cfg.ts_time_col if cfg else None)
    ts_kind = (cfg.ts_kind if cfg else "date") or "date"
    pk_cols = (pk if pk is not None else (cfg.primary_key_columns if cfg else None)) or None
    # Effective ON CONFLICT key (prompt 36): PK, or the sequence marker itself, or None → full-reload.
    upsert_key = upsert_key_for(ts_col, ts_kind == "sequence", pk_cols)
    full = not (ts_col and upsert_key)
    return {
        "source_view": table.table,
        "target_table": table.target_table,
        "label": table.label,
        "enabled": bool(cfg.enabled) if cfg else False,
        "ts_col": ts_col,
        "ts_time_col": cfg.ts_time_col if cfg else None,
        "ts_kind": ts_kind,
        "granularity": gran,
        "poll_interval_sec": cfg.poll_interval_sec if cfg else 300,
        "lookback_days": cfg.lookback_days if cfg else 1,
        "primary_key_columns": pk_cols,
        # Effective upsert key + its kind (prompt 36): drives the Streaming "key" badge + mode.
        "effective_upsert_key": upsert_key,
        "upsert_key_kind": ("primary_key" if pk_cols else ("marker" if upsert_key else None)),
        # 2-case mode: incremental (watermark + a usable key) vs full-reload (atomic swap, ≥12h).
        "mode": "full" if full else "incremental",
        "min_interval_sec": FULL_RELOAD_MIN_INTERVAL if full else MIN_INTERVAL,
        "last_watermark": cfg.last_watermark if cfg else None,
        "last_watermark_time": cfg.last_watermark_time if cfg else None,
        "last_run_at": cfg.last_run_at.isoformat() if cfg and cfg.last_run_at else None,
        "last_rows_added": cfg.last_rows_added if cfg else None,
        "last_status": cfg.last_status if cfg else None,
        "last_error": cfg.last_error if cfg else None,
        "has_ts_time_col": bool(cfg.ts_time_col) if cfg else False,
    }


def list_config_views(db: Session) -> list[dict[str, Any]]:
    saved = list_configs(db)
    pks = _all_job_pks(db)  # canonical PK per table (one query) so the Streaming PK cell is accurate
    return [config_view(saved.get(t.table.upper()), t, pk=pks.get(t.target_table)) for t in MIGRATABLE_TABLES]


# --- Oracle introspection (read-only) --------------------------------------------------------

def probe_view_columns(table: Ora2pgTable) -> tuple[list[str], str | None]:
    """Return (UPPER-cased column names of the view, error). Used to confirm a UPMT-style time
    column exists before enabling ``granularity=timestamp``. Read-only; runs in the ora2pg
    container. Returns ([], error) when Oracle is unreachable (e.g. the VPS)."""
    from app.services.source_count_service import _exec_perl, _oracle_dsn

    text_out, error = _exec_perl(
        _PROBE_COLS_PERL,
        "probe_cols.pl",
        {
            "ORA_DSN": _oracle_dsn(),
            "ORA_USER": settings.oracle_user or "",
            "ORA_PWD": settings.oracle_pwd or "",
            "ORA_VIEW": table.table.upper(),
        },
    )
    if error:
        return [], error
    cols = [line.split("\t", 1)[1] for line in text_out.splitlines() if line.startswith("COL\t")]
    return cols, (None if cols else (text_out.strip()[-200:] or "no columns / unreachable"))


def _job_pk(db: Session, table: Ora2pgTable) -> list[str] | None:
    """The canonical PK from migration_jobs.primary_key_columns (one source of truth shared with
    migrate/Repair). None if no job / not yet discovered."""
    job = db.scalar(select(MigrationJob).where(MigrationJob.name == f"ora2pg_{table.target_table}"))
    return (job.primary_key_columns or None) if job is not None else None


def _all_job_pks(db: Session) -> dict[str, list[str] | None]:
    """Batch the canonical PK for every ora2pg migration job → {target_table: pk_columns}. One query
    so ``list_config_views`` (40 tables) doesn't do 40 round-trips to colour the Streaming PK cell."""
    rows = db.scalars(select(MigrationJob).where(MigrationJob.name.like("ora2pg_%"))).all()
    out: dict[str, list[str] | None] = {}
    for r in rows:
        if r.name.startswith("ora2pg_"):
            out[r.name[len("ora2pg_"):]] = (r.primary_key_columns or None)
    return out


def effective_pk(db: Session, table: Ora2pgTable, cfg: StreamingConfig | None) -> list[str] | None:
    """Canonical PK for a streaming table: migration_jobs.primary_key_columns (set in the Streaming
    PK editor / discover-keys / reference seed), else the config's own synced copy."""
    return _job_pk(db, table) or (cfg.primary_key_columns if cfg else None)


def upsert_key_for(ts_col: str | None, sequence: bool, pk: list[str] | None) -> list[str] | None:
    """The effective ON CONFLICT key for Case-A streaming (prompt 36):
      - a real PK             → the PK columns
      - no PK + sequence marker (a unique monotonic id, e.g. ILUKID) → the marker itself is the key
      - otherwise (no PK + date marker, or no marker) → None → the table must full-reload (Case B).
    The marker can only be the key when it is a sequence/id: a date repeats within a day, so it can't
    dedup. ``None`` here is exactly the Case-B signal."""
    if pk:
        return pk
    if ts_col and sequence:
        return [ts_col]
    return None


def _discover_pk(table: Ora2pgTable) -> list[str] | None:
    """Best-effort PK discovery for one table (reuses the ora2pg-container introspection)."""
    try:
        out = ora2pg_runner.discover_oracle_keys([table])
        for r in out.get("results", []):
            if r.get("source_view", "").upper() == table.table.upper():
                return r.get("pk_columns")
    except Exception:  # pragma: no cover - discovery must never crash a cycle
        return None
    return None


# --- one streaming cycle ---------------------------------------------------------------------

def run_cycle(db: Session, cfg: StreamingConfig, *, force: bool = False) -> dict[str, Any]:
    """Run one streaming cycle for ``cfg`` and persist the cursor/status. Never raises.

    ``force`` ignores the ``enabled`` flag (used by the manual ``run-once`` endpoint)."""
    table = get_table(cfg.source_view)
    if table is None:
        return {"ok": False, "table": cfg.source_view, "skipped": True, "error": "unknown table"}
    if not cfg.enabled and not force:
        return {"ok": False, "table": table.table, "skipped": True, "error": "disabled"}

    # Authoritative: the saved ts_col IS the choice (None/"" → Case B full-reload). No hint fallback.
    ts_col = (cfg.ts_col or "").strip() or None
    sequence = (cfg.ts_kind or "date") == "sequence"

    # Canonical PK = migration_jobs.primary_key_columns (seeded from reference / set by discover-keys
    # / the Streaming PK editor), then the config's own copy. NO live auto-discovery here: a CLEARED
    # PK must STAY cleared, and a per-cycle Oracle round-trip would be wasteful. PK is configured
    # explicitly (now in the Streaming tab), not re-guessed every cycle.
    pk = effective_pk(db, table, cfg)
    if pk and cfg.primary_key_columns != pk:
        cfg.primary_key_columns = pk

    # ---- Upsert-key rule (prompt 36) — the marker (watermark) decides WHICH rows to pull; the
    # upsert key decides how to DEDUP on write. Two distinct roles:
    #   has PK                              → Case A, ON CONFLICT(PK)
    #   no PK + sequence marker (unique id) → Case A, the MARKER ITSELF is the key (unique index on it)
    #   no PK + date marker (NOT unique)    → Case B full-reload (a date can't dedup: many rows/day)
    #   no watermark column                 → Case B full-reload (nothing to increment on)
    upsert_key = upsert_key_for(ts_col, sequence, pk)

    # ---- Case B: no watermark column OR no usable upsert key → FULL-RELOAD + atomic swap ----
    if not ts_col or not upsert_key:
        res = ora2pg_runner.full_reload_once(table, pk_columns=pk)
        if not ts_col:
            why = "no watermark column"
        elif not pk:
            why = "no primary key + date watermark (a date is not a unique key)"
        else:
            why = "no primary key"
        return _finish(
            db, cfg, table, ok=bool(res.get("ok")),
            status=("ok" if res.get("ok") else "error"), error=res.get("error"),
            rows_added=res.get("rows_added"), predicate=f"(full reload — atomic swap; {why})", extra=res,
        )

    # ---- Case A: incremental (date OR sequence) — has a watermark column AND an upsert key ----
    # (the upsert key is the PK, or the sequence marker itself when there is no PK). The unique index
    # the upsert needs is (re)built by streaming_pull_once → a non-unique marker fails there with a
    # clear error and never advances the cursor / persists a bad key.
    if not ora2pg_runner.target_exists(table.target_table):
        return _finish(db, cfg, table, ok=False, status="error",
                       error="target table missing — run an initial full load before streaming")

    gran = effective_granularity(cfg.granularity, cfg.ts_time_col)
    time_col = cfg.ts_time_col if (gran == "timestamp" and not sequence) else None

    # Initialise the cursor from the loaded baseline (only rows newer than what's loaded stream in).
    if cfg.last_watermark is None:
        d0, t0 = ora2pg_runner.target_max_watermark(table.target_table, ts_col, time_col, numeric=sequence)
        cfg.last_watermark = d0 if d0 is not None else "0"
        cfg.last_watermark_time = t0 if not sequence else None

    predicate = build_streaming_predicate(
        table.table, ts_col,
        ts_time_col=cfg.ts_time_col, granularity=gran,
        cursor_day=cfg.last_watermark, cursor_time=cfg.last_watermark_time,
        lookback_days=cfg.lookback_days, sequence=sequence,
    )

    res = ora2pg_runner.streaming_pull_once(table, where_clause=predicate, pk_columns=upsert_key)

    if res.get("ok"):
        d2, t2 = ora2pg_runner.target_max_watermark(table.target_table, ts_col, time_col, numeric=sequence)
        if d2 is not None:
            cfg.last_watermark = d2
            if gran == "timestamp" and not sequence:
                cfg.last_watermark_time = t2
        return _finish(db, cfg, table, ok=True, status="ok", error=None,
                       rows_added=res.get("rows_added"), predicate=predicate, extra=res)
    return _finish(db, cfg, table, ok=False, status="error", error=res.get("error"),
                   rows_added=res.get("rows_added"), predicate=predicate, extra=res)


def _finish(
    db: Session,
    cfg: StreamingConfig,
    table: Ora2pgTable,
    *,
    ok: bool,
    status: str,
    error: str | None,
    rows_added: int | None = None,
    predicate: str | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    cfg.last_run_at = datetime.now(timezone.utc)
    cfg.last_status = status
    cfg.last_error = (error or "")[:4000] or None
    if rows_added is not None:
        cfg.last_rows_added = rows_added
    db.add(cfg)
    db.commit()
    db.refresh(cfg)
    payload = {
        "ok": ok,
        "table": table.table,
        "status": status,
        "predicate": predicate,
        "rows_added": rows_added,
        "cursor": cfg.last_watermark,
        "cursor_time": cfg.last_watermark_time,
        "error": error,
    }
    if extra:
        payload["rows_before"] = extra.get("rows_before")
        payload["rows_after"] = extra.get("rows_after")
        payload["exit_code"] = extra.get("exit_code")
    logger.info("streaming cycle %s: %s", table.table, {k: payload[k] for k in ("status", "rows_added", "cursor", "error")})
    return payload


# Absolute floor (seconds) for an incremental table — the Settings "Interval (s)" field is the
# single, real control (honoured exactly down to this floor); this just stops the loop busy-spinning.
MIN_INTERVAL = 2

# Case-B (full-reload) is expensive (full COPY + ~2× space) → a HARD 12h floor + 24h default so a
# mis-set cadence can't hammer Oracle / disk. Enforced both here (scheduling) and at PUT (clamp).
FULL_RELOAD_MIN_INTERVAL = 43200   # 12h
FULL_RELOAD_DEFAULT_INTERVAL = 86400  # 24h


def is_full_reload(cfg: StreamingConfig, pk: list[str] | None = None) -> bool:
    """A table streams in full-reload mode (12h floor) when it has no usable upsert key for an
    incremental pull (prompt 36 — same rule as run_cycle / config_view; NO catalog-hint fallback):
      - no watermark column                 → full
      - sequence marker (the marker is its own key) → incremental
      - date marker WITH a PK               → incremental (ON CONFLICT(PK))
      - date marker WITHOUT a PK            → full (a date can't dedup).
    ``pk`` should be the CANONICAL PK (effective_pk); falls back to the config's synced copy so the
    scheduling floor agrees with config_view / put_config (which use effective_pk) instead of a
    possibly-stale cfg copy."""
    ts_col = (cfg.ts_col or "").strip() or None
    if not ts_col:
        return True
    sequence = (cfg.ts_kind or "date") == "sequence"
    pk_cols = pk if pk is not None else (cfg.primary_key_columns or None)
    return not bool(upsert_key_for(ts_col, sequence, pk_cols))


def effective_interval(cfg: StreamingConfig, pk: list[str] | None = None) -> int:
    """The real cadence floor for a table: incremental → MIN_INTERVAL; full-reload → 12h floor."""
    if is_full_reload(cfg, pk):
        return max(FULL_RELOAD_MIN_INTERVAL, int(cfg.poll_interval_sec or FULL_RELOAD_DEFAULT_INTERVAL))
    return max(MIN_INTERVAL, int(cfg.poll_interval_sec or 60))


def run_all_due(db: Session) -> dict[str, Any]:
    """Run a cycle for every enabled config that is due, and report the sleep the poll loop should
    use next = the smallest enabled effective interval (full-reload tables floored at 12h). The
    full-reload decision uses the CANONICAL job PK (batched) so an incremental table whose PK lives
    only in migration_jobs is never throttled to the 12h floor."""
    now = datetime.now(timezone.utc)
    pks = _all_job_pks(db)

    def _pk_for(cfg: StreamingConfig) -> list[str] | None:
        t = get_table(cfg.source_view)
        return (pks.get(t.target_table) if t else None) or (cfg.primary_key_columns or None)

    results: list[dict[str, Any]] = []
    enabled = db.scalars(select(StreamingConfig).where(StreamingConfig.enabled.is_(True))).all()
    for cfg in enabled:
        interval = effective_interval(cfg, _pk_for(cfg))
        if cfg.last_run_at is not None:
            last = cfg.last_run_at
            if last.tzinfo is None:
                last = last.replace(tzinfo=timezone.utc)
            if (now - last).total_seconds() < interval:
                continue  # not due yet
        results.append(run_cycle(db, cfg))
    intervals = [effective_interval(c, _pk_for(c)) for c in enabled]
    next_interval = min(intervals) if intervals else None
    return {"ran": len(results), "results": results, "next_interval": next_interval}

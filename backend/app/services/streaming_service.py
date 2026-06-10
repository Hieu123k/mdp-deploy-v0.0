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


def config_view(cfg: StreamingConfig | None, table: Ora2pgTable) -> dict[str, Any]:
    """Serialise a config (saved row or catalog default) for the API."""
    # Authoritative: a saved row's ts_col IS the choice (None/"" → full-reload). The catalog hint is
    # only a suggestion when no row exists yet.
    ts_col = ((cfg.ts_col or "").strip() or None) if cfg else _default_ts_col(table)
    gran = effective_granularity(cfg.granularity if cfg else "day", cfg.ts_time_col if cfg else None)
    full = not ts_col
    return {
        "source_view": table.table,
        "target_table": table.target_table,
        "label": table.label,
        "enabled": bool(cfg.enabled) if cfg else False,
        "ts_col": ts_col,
        "ts_time_col": cfg.ts_time_col if cfg else None,
        "ts_kind": (cfg.ts_kind if cfg else "date"),
        "granularity": gran,
        "poll_interval_sec": cfg.poll_interval_sec if cfg else 300,
        "lookback_days": cfg.lookback_days if cfg else 1,
        "primary_key_columns": (cfg.primary_key_columns if cfg else None),
        # 2-case mode (prompt 35): incremental (watermark) vs full-reload (atomic swap, ≥12h).
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
    return [config_view(saved.get(t.table.upper()), t) for t in MIGRATABLE_TABLES]


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

    # Canonical PK = migration_jobs.primary_key_columns (seeded from reference / set by discover-keys
    # / the dashboard PK editor), then the config's own copy. NO live auto-discovery here: a CLEARED
    # PK must STAY cleared (so the table deliberately falls to Case B full-reload), and a per-cycle
    # Oracle round-trip would be wasteful. PK is configured explicitly, not re-guessed every cycle.
    pk = _job_pk(db, table) or cfg.primary_key_columns
    if pk and cfg.primary_key_columns != pk:
        cfg.primary_key_columns = pk

    # ---- Case B: NO watermark column OR NO primary key → FULL-RELOAD + atomic swap ----
    # (no ts_col = nothing to increment on; no PK = can't upsert → both fall to a full re-copy.)
    if not ts_col or not pk:
        res = ora2pg_runner.full_reload_once(table, pk_columns=pk)
        why = "no watermark column" if not ts_col else "no primary key (cleared)"
        return _finish(
            db, cfg, table, ok=bool(res.get("ok")),
            status=("ok" if res.get("ok") else "error"), error=res.get("error"),
            rows_added=res.get("rows_added"), predicate=f"(full reload — atomic swap; {why})", extra=res,
        )

    # ---- Case A: incremental (date OR sequence) — has both a watermark column AND a PK ----
    if not ora2pg_runner.target_exists(table.target_table):
        return _finish(db, cfg, table, ok=False, status="error",
                       error="target table missing — run an initial full load before streaming")

    sequence = (cfg.ts_kind or "date") == "sequence"
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

    res = ora2pg_runner.streaming_pull_once(table, where_clause=predicate, pk_columns=pk)

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


def is_full_reload(cfg: StreamingConfig) -> bool:
    """A table streams in full-reload mode when its SAVED ts_col is empty (authoritative — same rule
    as run_cycle / config_view; NO catalog-hint fallback, else the 12h floor would be bypassed for
    the hint tables F0911/F0411/F4311)."""
    return not ((cfg.ts_col or "").strip() or None)


def effective_interval(cfg: StreamingConfig) -> int:
    """The real cadence floor for a table: incremental → MIN_INTERVAL; full-reload → 12h floor."""
    if is_full_reload(cfg):
        return max(FULL_RELOAD_MIN_INTERVAL, int(cfg.poll_interval_sec or FULL_RELOAD_DEFAULT_INTERVAL))
    return max(MIN_INTERVAL, int(cfg.poll_interval_sec or 60))


def run_all_due(db: Session) -> dict[str, Any]:
    """Run a cycle for every enabled config that is due, and report the sleep the poll loop should
    use next = the smallest enabled effective interval (full-reload tables floored at 12h)."""
    now = datetime.now(timezone.utc)
    results: list[dict[str, Any]] = []
    enabled = db.scalars(select(StreamingConfig).where(StreamingConfig.enabled.is_(True))).all()
    for cfg in enabled:
        interval = effective_interval(cfg)
        if cfg.last_run_at is not None:
            last = cfg.last_run_at
            if last.tzinfo is None:
                last = last.replace(tzinfo=timezone.utc)
            if (now - last).total_seconds() < interval:
                continue  # not due yet
        results.append(run_cycle(db, cfg))
    intervals = [effective_interval(c) for c in enabled]
    next_interval = min(intervals) if intervals else None
    return {"ran": len(results), "results": results, "next_interval": next_interval}

"""One-time, ADMIN-RUN backfill of historical dm_* timestamps (prompt 39, Hướng C).

dm_* ``created_at``/``updated_at`` rows written BEFORE the timezone fix (prompt 39 A/B) hold UTC
wall-clock. This shifts them to local (VN) wall-clock by ``+hours`` (default 7). It is:

  * DRY-RUN by default (counts only, writes nothing);
  * GUARDED by ``mdp_data._tz_backfill_log`` (table_name, shifted_hours, cutoff) so it can never
    double-shift a table; the log records the apply params so REVERSE is faithful to them;
  * REVERSIBLE for a WHOLE-TABLE apply (``reverse=True`` subtracts the LOGGED hours — not the CLI
    ``--hours`` — and clears the guard). A ``--cutoff``-scoped apply is NOT cleanly reversible (after
    +Δ the shifted rows overlap the unshifted [cutoff, cutoff+Δ) window, so no predicate can re-select
    exactly the shifted set) → reverse REFUSES it (fail-closed) rather than corrupt post-fix rows;
  * scoped to ``mdp_data.dm_*`` only (system timestamptz tables are never touched);
  * NOT wired into any automatic path — an admin runs it manually after verifying the dry-run.

🔴 Do NOT run on real data without an explicit dry-run review first.

CLI:  python -m app.services.tz_backfill --dry-run        # count what would change (default)
      python -m app.services.tz_backfill --apply          # shift +7h, record the guard
      python -m app.services.tz_backfill --apply --reverse # undo a prior shift
      python -m app.services.tz_backfill --apply --cutoff '2026-06-11T00:00:00'  # only rows before the fix
"""
from __future__ import annotations

import argparse
import re
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services.table_generator import ensure_mdp_data_schema_exists

_DM_TABLE_RE = re.compile(r"^dm_[a-z0-9_]*$")
DEFAULT_SHIFT_HOURS = 7
_LOG_TABLE = '"mdp_data"."_tz_backfill_log"'


def _is_postgres(db: Session) -> bool:
    return bool(db.bind and db.bind.dialect.name == "postgresql")


def _log_exists(db: Session) -> bool:
    return db.execute(text("SELECT to_regclass('mdp_data._tz_backfill_log')")).scalar() is not None


def _ensure_log_table(db: Session) -> None:
    ensure_mdp_data_schema_exists(db)
    db.execute(
        text(
            f"CREATE TABLE IF NOT EXISTS {_LOG_TABLE} ("
            "table_name text PRIMARY KEY, shifted_hours integer NOT NULL, "
            "cutoff text NULL, "  # the cutoff used by apply, so reverse is faithful to the apply
            "applied_at timestamptz NOT NULL DEFAULT now())"
        )
    )
    # Forward-compat for a log table created before the cutoff column existed.
    db.execute(text(f"ALTER TABLE {_LOG_TABLE} ADD COLUMN IF NOT EXISTS cutoff text NULL"))


def _dm_tables(db: Session, only_tables: list[str] | None) -> list[str]:
    rows = db.execute(
        text(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'mdp_data' AND table_name LIKE 'dm\\_%' ESCAPE '\\' "
            "ORDER BY table_name"
        )
    ).fetchall()
    names = [r[0] for r in rows if _DM_TABLE_RE.fullmatch(r[0])]
    if only_tables:
        wanted = {t for t in only_tables if _DM_TABLE_RE.fullmatch(t)}
        names = [n for n in names if n in wanted]
    return names


def backfill_dm_timestamps(
    db: Session,
    *,
    dry_run: bool = True,
    reverse: bool = False,
    hours: int = DEFAULT_SHIFT_HOURS,
    only_tables: list[str] | None = None,
    cutoff: Any = None,
) -> dict[str, Any]:
    """Shift dm_* created_at/updated_at by ``±hours`` (VN wall-clock). DRY-RUN counts only. The
    ``_tz_backfill_log`` guard makes ``apply`` idempotent (a logged table is skipped) and ``reverse``
    only acts on logged tables. ``cutoff`` (optional) limits to rows with ``created_at < cutoff`` (the
    rows written before the fix). Returns a structured plan/result."""
    if not _is_postgres(db):
        return {"dry_run": dry_run, "reverse": reverse, "hours": hours, "tables": [],
                "total_rows": 0, "note": "postgres-only (dm_* tables do not exist on this dialect)"}

    if not dry_run:
        _ensure_log_table(db)

    # Load the FULL guard log (per-table apply params) so reverse is faithful to what apply did,
    # independent of the CLI flags passed to the reverse invocation.
    logged: dict[str, dict[str, Any]] = {}
    if _log_exists(db):
        for row in db.execute(
            text(f"SELECT table_name, shifted_hours, cutoff FROM {_LOG_TABLE}")
        ).mappings():
            logged[row["table_name"]] = {"hours": int(row["shifted_hours"]), "cutoff": row["cutoff"]}

    fwd_where = ""
    fwd_params: dict[str, Any] = {"h": int(hours)}
    if cutoff is not None:
        fwd_where = " WHERE created_at < :cutoff"
        fwd_params["cutoff"] = cutoff

    results: list[dict[str, Any]] = []
    total = 0
    for table in _dm_tables(db, only_tables):
        ref = f'"mdp_data"."{table}"'
        if reverse:
            entry = logged.get(table)
            if entry is None:
                results.append({"table": table, "rows": 0, "status": "skip (not backfilled)"})
                continue
            # A cutoff-scoped forward shift is NOT cleanly reversible: after +Δ, the shifted rows
            # overlap the unshifted [cutoff, cutoff+Δ) window, so no created_at predicate can re-select
            # exactly the shifted set. Refuse rather than corrupt the un-shifted (post-fix) rows.
            if entry["cutoff"] is not None:
                results.append({
                    "table": table, "rows": 0,
                    "status": f"REFUSED (apply used --cutoff {entry['cutoff']}; exact reverse impossible — restore from backup)",
                })
                continue
            rev_hours = entry["hours"]  # use the LOGGED magnitude, never the CLI --hours
            count = int(db.execute(text(f"SELECT count(*) FROM {ref}")).scalar() or 0)
            if not dry_run:
                db.execute(text(
                    f"UPDATE {ref} SET created_at = created_at - make_interval(hours => :h), "
                    "updated_at = updated_at - make_interval(hours => :h)"
                ), {"h": rev_hours})
                db.execute(text(f"DELETE FROM {_LOG_TABLE} WHERE table_name = :t"), {"t": table})
            results.append({"table": table, "rows": count,
                            "status": (f"would reverse -{rev_hours}h" if dry_run else f"reversed -{rev_hours}h")})
            total += count
        else:
            if table in logged:
                results.append({"table": table, "rows": 0, "status": "skip (already backfilled)"})
                continue
            count = int(db.execute(text(f"SELECT count(*) FROM {ref}{fwd_where}"), fwd_params).scalar() or 0)
            if not dry_run:
                db.execute(text(
                    f"UPDATE {ref} SET created_at = created_at + make_interval(hours => :h), "
                    f"updated_at = updated_at + make_interval(hours => :h){fwd_where}"
                ), fwd_params)
                db.execute(text(
                    f"INSERT INTO {_LOG_TABLE} (table_name, shifted_hours, cutoff) VALUES (:t, :h, :cutoff) "
                    "ON CONFLICT (table_name) DO NOTHING"
                ), {"t": table, "h": int(hours), "cutoff": (str(cutoff) if cutoff is not None else None)})
            results.append({"table": table, "rows": count,
                            "status": (f"would shift +{hours}h" if dry_run else f"shifted +{hours}h")})
            total += count

    if not dry_run:
        db.commit()
    return {"dry_run": dry_run, "reverse": reverse, "hours": int(hours),
            "cutoff": str(cutoff) if cutoff is not None else None, "tables": results, "total_rows": total}


def _main() -> None:  # pragma: no cover - CLI wrapper
    parser = argparse.ArgumentParser(description="Backfill dm_* timestamps UTC → local wall-clock (admin-run).")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="count only, write nothing (default)")
    mode.add_argument("--apply", action="store_true", help="perform the shift (writes data)")
    parser.add_argument("--reverse", action="store_true", help="subtract the hours and clear the guard")
    parser.add_argument("--hours", type=int, default=DEFAULT_SHIFT_HOURS)
    parser.add_argument("--cutoff", default=None, help="only rows with created_at < CUTOFF (ISO ts)")
    parser.add_argument("--tables", nargs="*", default=None, help="limit to these dm_* tables")
    args = parser.parse_args()

    from app.db.session import SessionLocal

    dry_run = not args.apply  # default dry-run; --apply opts into writing
    with SessionLocal() as db:
        result = backfill_dm_timestamps(
            db, dry_run=dry_run, reverse=args.reverse, hours=args.hours,
            only_tables=args.tables, cutoff=args.cutoff,
        )
    import json

    print(json.dumps(result, indent=2))


if __name__ == "__main__":  # pragma: no cover
    _main()

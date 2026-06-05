"""Source-count cache for the Migration dashboard.

The periodic refresher fills ``ora2pg_source_counts`` with cheap ESTIMATE counts (Oracle table
stats) so the `Source` column shows a number for every table on page load. Exact counts run
on-demand (Verify). All Oracle access goes through the ora2pg container (Perl/DBI), reusing the
``discover_oracle_keys`` infrastructure; the two ``*_oracle_count*`` helpers are the only places
that touch Oracle and are easily mocked in tests. Nothing here raises — failures degrade to a
``stale`` cache row.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.ora2pg_catalog import Ora2pgTable
from app.models.source_count import Ora2pgSourceCount
from app.services.ora2pg_runner import _open_ora2pg

# Perl/DBI run INSIDE the ora2pg container (creds via exec env — never logged). estimate reads
# ALL_TABLES.NUM_ROWS for the base JDE tables (views have no stats); exact does COUNT(*) on the
# view (same SELECT-view grant the migration uses, so it always works where migrate works).
_ESTIMATE_PERL = r"""
use strict; use warnings; use DBI;
my $dbh = DBI->connect($ENV{ORA_DSN}, $ENV{ORA_USER}, $ENV{ORA_PWD},
                       { RaiseError => 1, AutoCommit => 1, PrintError => 0 });
my $tin = join(",", map { "'".$_."'" } split /,/, ($ENV{ORA_TABLES} // ""));
if ($tin ne "") {
  my $s = $dbh->prepare(qq{ SELECT table_name, num_rows FROM all_tables WHERE table_name IN ($tin) });
  $s->execute();
  while (my @r = $s->fetchrow_array()) { print "EST\t$r[0]\t".(defined $r[1] ? $r[1] : "")."\n"; }
}
$dbh->disconnect();
"""

_EXACT_PERL = r"""
use strict; use warnings; use DBI;
my $dbh = DBI->connect($ENV{ORA_DSN}, $ENV{ORA_USER}, $ENV{ORA_PWD},
                       { RaiseError => 1, AutoCommit => 1, PrintError => 0 });
my $schema = $ENV{ORA_SCHEMA} // "";
my $view = $ENV{ORA_VIEW};
my $tbl = $schema ne "" ? "$schema.$view" : $view;
my $s = $dbh->prepare("SELECT COUNT(*) FROM $tbl");
$s->execute();
my ($c) = $s->fetchrow_array();
print "EXACT\t$view\t$c\n";
$dbh->disconnect();
"""


def _oracle_dsn() -> str:
    dsn = f"dbi:Oracle:host={settings.oracle_host};port={settings.oracle_port}"
    if settings.oracle_service_name:
        dsn += f";service_name={settings.oracle_service_name}"
    elif settings.oracle_sid:
        dsn += f";sid={settings.oracle_sid}"
    return dsn


def _exec_perl(script: str, filename: str, env: dict[str, str]) -> tuple[str, str | None]:
    """Run a Perl script in the ora2pg container. Returns (stdout, error). Never raises."""
    try:
        api, container = _open_ora2pg()
    except Exception as exc:
        return "", f"ora2pg container unavailable: {exc}"
    try:
        with open(os.path.join(settings.ora2pg_shared_dir, filename), "w", encoding="utf-8") as fh:
            fh.write(script)
        exec_id = api.exec_create(
            container.id, cmd=["perl", f"/config/{filename}"], environment=env, stdout=True, stderr=True
        )["Id"]
        out = api.exec_start(exec_id)
        text_out = out.decode("utf-8", "replace") if isinstance(out, (bytes, bytearray)) else str(out)
        return text_out, None
    except Exception as exc:
        return "", f"exec failed: {exc}"


def estimate_oracle_counts(tables: list[Ora2pgTable]) -> dict[str, dict[str, Any]]:
    """ESTIMATE source rows for each view via the base table's ALL_TABLES.NUM_ROWS.
    Returns {SOURCE_VIEW: {"count": int|None, "error": str|None}}. Never raises (Oracle → .63)."""
    base_to_view = {t.table.upper().replace("V2_PRO_", "", 1): t.table.upper() for t in tables}
    out: dict[str, dict[str, Any]] = {v: {"count": None, "error": "not counted"} for v in base_to_view.values()}

    text_out, error = _exec_perl(
        _ESTIMATE_PERL, "source_estimate.pl",
        {"ORA_DSN": _oracle_dsn(), "ORA_USER": settings.oracle_user or "",
         "ORA_PWD": settings.oracle_pwd or "", "ORA_TABLES": ",".join(base_to_view.keys())},
    )
    if error is not None or "EST\t" not in text_out:
        msg = error or "oracle unreachable / no stats"
        for v in out:
            out[v]["error"] = msg
        return out

    base_counts: dict[str, int] = {}
    for line in text_out.splitlines():
        p = line.split("\t")
        if p[0] == "EST" and len(p) == 3 and p[2].strip():
            try:
                n = int(p[2])
            except ValueError:
                continue
            base_counts[p[1].upper()] = max(base_counts.get(p[1].upper(), 0), n)

    for base, view in base_to_view.items():
        if base in base_counts:
            out[view] = {"count": base_counts[base], "error": None}
        else:
            out[view] = {"count": None, "error": "no NUM_ROWS (stats missing or no privilege)"}
    return out


def exact_oracle_count(table: Ora2pgTable) -> dict[str, Any]:
    """Exact COUNT(*) on the Oracle view. Returns {"count": int|None, "error": str|None}."""
    text_out, error = _exec_perl(
        _EXACT_PERL, "source_exact.pl",
        {"ORA_DSN": _oracle_dsn(), "ORA_USER": settings.oracle_user or "",
         "ORA_PWD": settings.oracle_pwd or "", "ORA_SCHEMA": settings.oracle_schema or "",
         "ORA_VIEW": table.table.upper()},
    )
    if error is not None or "EXACT\t" not in text_out:
        return {"count": None, "error": error or "oracle unreachable"}
    for line in text_out.splitlines():
        p = line.split("\t")
        if p[0] == "EXACT" and len(p) == 3:
            try:
                return {"count": int(p[2]), "error": None}
            except ValueError:
                return {"count": None, "error": "bad count output"}
    return {"count": None, "error": "no count output"}


# --------------------------------------------------------------- cache CRUD
def upsert_source_count(
    db: Session, *, source_view: str, target_table: str | None, count: int | None,
    mode: str, approximate: bool, status: str, last_error: str | None = None,
) -> Ora2pgSourceCount:
    """Upsert a cache row. On a non-ok status the previous good count is KEPT (only status /
    last_error update) so a transient Oracle failure never wipes a usable number."""
    row = db.scalar(select(Ora2pgSourceCount).where(Ora2pgSourceCount.source_view == source_view))
    if row is None:
        row = Ora2pgSourceCount(source_view=source_view)
        db.add(row)
    row.target_table = target_table
    if status == "ok":
        row.source_row_count = count
        row.count_mode = mode
        row.approximate = approximate
        row.counted_at = datetime.now(timezone.utc)
    row.status = status
    row.last_error = last_error
    db.commit()
    db.refresh(row)
    return row


def get_all_source_counts(db: Session) -> dict[str, Ora2pgSourceCount]:
    return {r.source_view.upper(): r for r in db.scalars(select(Ora2pgSourceCount))}


def refresh_estimates(db: Session, tables: list[Ora2pgTable]) -> dict[str, int]:
    """One estimate cycle: count via Oracle stats and upsert every table. Failures → stale."""
    counts = estimate_oracle_counts(tables)
    ok = stale = 0
    for t in tables:
        c = counts.get(t.table.upper(), {"count": None, "error": "missing"})
        if c["error"] is None and c["count"] is not None:
            upsert_source_count(
                db, source_view=t.table, target_table=t.target_table, count=c["count"],
                mode="estimate", approximate=True, status="ok",
            )
            ok += 1
        else:
            upsert_source_count(
                db, source_view=t.table, target_table=t.target_table, count=None,
                mode="estimate", approximate=True, status="stale", last_error=c["error"],
            )
            stale += 1
    return {"ok": ok, "stale": stale, "total": len(tables)}


def verify_exact(db: Session, table: Ora2pgTable) -> Ora2pgSourceCount | None:
    """On-demand exact count for one table -> cache (mode=exact). Failure keeps the old row stale.
    Returns the (refreshed) cache row, or None if Oracle was unreachable and no row exists yet."""
    result = exact_oracle_count(table)
    if result["error"] is None and result["count"] is not None:
        return upsert_source_count(
            db, source_view=table.table, target_table=table.target_table, count=result["count"],
            mode="exact", approximate=False, status="ok",
        )
    return upsert_source_count(
        db, source_view=table.table, target_table=table.target_table, count=None,
        mode="exact", approximate=False, status="stale", last_error=result["error"],
    )


def source_verdict(row: Ora2pgSourceCount | None, current_rows: int | None) -> str:
    """MATCH/MISMATCH only from an EXACT source count; an estimate yields ESTIMATE (never a red
    MISMATCH), and no usable count yields PENDING."""
    if row is None or row.source_row_count is None:
        return "PENDING"
    if row.count_mode == "exact" and not row.approximate:
        if current_rows is None:
            return "PENDING"
        return "MATCH" if row.source_row_count == current_rows else "MISMATCH"
    return "ESTIMATE"

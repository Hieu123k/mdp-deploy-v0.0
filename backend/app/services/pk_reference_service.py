"""Primary-Key REFERENCE seed (public JDE 9.20 vanilla PKs) — the DEFAULT source for every table.

PK now comes from exactly two sources: (1) this public-doc reference = default (seeded), and (2)
admin manual edit = override. Auto-scan (discover-keys) is OPTIONAL. The reference is loaded from
``app/core/jde_default_primary_keys.json`` (generated from handoff/reference/...csv) and seeded into
the canonical ``migration_jobs.primary_key_columns`` (+ ``config.pk_source='reference'``) at startup,
idempotently and WITHOUT ever overriding a manual PK. No Oracle/target access is needed to seed —
column mismatches with the actual view are surfaced as warnings / validated at use-time.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.core.ora2pg_catalog import MIGRATABLE_TABLES

_REF_PATH = Path(__file__).resolve().parent.parent / "core" / "jde_default_primary_keys.json"


def _load() -> dict[str, dict[str, Any]]:
    try:
        data = json.loads(_REF_PATH.read_text(encoding="utf-8"))
        return {r["source_view"].upper(): r for r in data.get("tables", [])}
    except Exception:  # missing/bad reference must never break startup
        return {}


REFERENCE: dict[str, dict[str, Any]] = _load()


def reference_meta(source_view: str) -> dict[str, Any] | None:
    return REFERENCE.get((source_view or "").upper())


def reference_pk(source_view: str) -> list[str] | None:
    """Reference PK mapped to target/view column names = the physical base columns lower-cased
    (the V2_PRO_ views keep physical names → lower-case is the 1:1 map). A view that de-prefixes is
    caught by the missing-column warning / use-time validation."""
    r = reference_meta(source_view)
    if not r:
        return None
    return [c.lower() for c in r.get("pk_columns_physical", []) if c]


def seed_reference_primary_keys(db: Session) -> int:
    """Idempotent seed: for every catalog table present in the reference, set the canonical PK +
    ``config.pk_source='reference'`` + reference flags, UNLESS the table already has a manual
    override OR a scanned (discovered) PK — priority is manual > scanned > reference, so re-seeding
    on every boot must never silently revert a deliberately-set or empirically-discovered PK back to
    the reference guess. Returns the number seeded."""
    from app.api.ora2pg_dashboard import _get_or_create_job  # lazy: avoid import cycle

    seeded = 0
    for t in MIGRATABLE_TABLES:
        ref = REFERENCE.get(t.table.upper())
        if not ref:
            continue
        job = _get_or_create_job(db, t)
        cfg = dict(job.config or {})
        if cfg.get("pk_source") in ("manual", "scanned"):
            continue  # manual/scanned always win — never revert a set PK to the reference default
        cfg.update({
            "pk_source": "reference",
            "pk_name_match": bool(ref.get("name_match")),
            "pk_type": ref.get("pk_type"),
            "pk_vanilla": ref.get("vanilla_name"),
        })
        job.primary_key_columns = [c.lower() for c in ref.get("pk_columns_physical", []) if c]
        job.config = cfg
        db.add(job)
        seeded += 1
    db.commit()
    return seeded

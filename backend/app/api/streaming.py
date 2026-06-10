"""Streaming (watermark-incremental) control API — additive, auth-gated.

Minimal REST surface to configure, inspect and manually trigger watermark streaming per table.
A polished Settings UI is a later prompt; this is enough to drive and verify the feature.
"""
from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_permission
from app.core.ora2pg_catalog import get_table
from app.db.session import get_db
from app.services import streaming_refresher, streaming_service

router = APIRouter(
    prefix="/streaming",
    tags=["streaming"],
    dependencies=[Depends(get_current_user)],
)


import re

_TS_COL_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")  # watermark column → identifier-safe (DDL/predicate injection)


class StreamingConfigUpdate(BaseModel):
    enabled: bool | None = None
    ts_col: str | None = None  # "" → clear (full-reload mode)
    ts_time_col: str | None = None
    ts_kind: str | None = None  # date | sequence
    granularity: str | None = None
    poll_interval_sec: int | None = None
    lookback_days: int | None = None
    primary_key_columns: list[str] | None = None


@router.get("/config")
def list_config(db: Annotated[Session, Depends(get_db)]) -> dict[str, Any]:
    return {"tables": streaming_service.list_config_views(db)}


@router.get("/config/{table_name}")
def get_config(table_name: str, db: Annotated[Session, Depends(get_db)]) -> dict[str, Any]:
    table = get_table(table_name)
    if table is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown table")
    cfg = streaming_service.get_config(db, table.table)
    return streaming_service.config_view(cfg, table, pk=streaming_service.effective_pk(db, table, cfg))


@router.put("/config/{table_name}", dependencies=[Depends(require_permission("streaming.configure"))])
def put_config(
    table_name: str,
    payload: StreamingConfigUpdate,
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    table = get_table(table_name)
    if table is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown table")

    fields = payload.model_dump(exclude_none=True)
    # PK / upsert key is pk.edit-gated: it MUST NOT be settable through streaming.configure. Strip it
    # here so a streaming.configure-only role can never write the upsert key via this back door (the FE
    # configures PK only through the pk.edit ora2pg endpoints, which sync streaming_configs).
    fields.pop("primary_key_columns", None)
    if "granularity" in fields and fields["granularity"] not in streaming_service.GRANULARITIES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="granularity must be day|timestamp")
    if "ts_kind" in fields and fields["ts_kind"] not in ("date", "sequence"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="ts_kind must be date|sequence")

    cfg_existing = streaming_service.get_config(db, table.table)
    new_ts_col = (
        (fields["ts_col"] or "").strip() if "ts_col" in fields
        else ((cfg_existing.ts_col or "").strip() if cfg_existing else "")
    )

    # Validate a chosen watermark column: identifier-safe (it is interpolated into the ora2pg WHERE)
    # AND, when the view can be probed, a real column of the view.
    if "ts_col" in fields and new_ts_col:
        if not _TS_COL_RE.fullmatch(new_ts_col):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="ts_col must be a column name (letters/digits/underscore)")
        cols, _err = streaming_service.probe_view_columns(table)
        if cols and new_ts_col.upper() not in {c.upper() for c in cols}:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"ts_col '{new_ts_col}' not found in view {table.table} (columns probed: {len(cols)})",
            )

    # ts_time_col is interpolated into the WHERE predicate too → identifier-gate it unconditionally
    # (same as ts_col), independent of the granularity field, so a two-request or off-Oracle path can't
    # smuggle a non-identifier into the predicate.
    if fields.get("ts_time_col") and not _TS_COL_RE.fullmatch(fields["ts_time_col"]):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="ts_time_col must be a column name (letters/digits/underscore)")

    # Case-B (full-reload) interval floor: a full-reload table copies the WHOLE view every cycle →
    # clamp poll_interval_sec to the 12h hard floor whenever the EFFECTIVE mode is full, even if this
    # request doesn't send poll_interval_sec (e.g. it only clears ts_col). The effective mode now
    # depends on the upsert key too (prompt 36): no watermark, OR a date marker with no PK → full.
    new_kind = fields.get("ts_kind") or (cfg_existing.ts_kind if cfg_existing else "date")
    pk_eff = (
        fields.get("primary_key_columns")
        or (cfg_existing.primary_key_columns if cfg_existing else None)
        or streaming_service.effective_pk(db, table, cfg_existing)
    )
    would_full = not bool(streaming_service.upsert_key_for(new_ts_col or None, new_kind == "sequence", pk_eff))
    if would_full:
        floor = streaming_service.FULL_RELOAD_MIN_INTERVAL
        current = int(fields.get("poll_interval_sec", cfg_existing.poll_interval_sec if cfg_existing else 0) or 0)
        if current < floor:
            fields["poll_interval_sec"] = floor

    # timestamp granularity needs a real time-of-day column — require it to be configured (in this
    # request or already saved) AND confirmed present in the view.
    if fields.get("granularity") == "timestamp":
        ts_time = fields.get("ts_time_col") or (cfg_existing.ts_time_col if cfg_existing else None)
        if not ts_time:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="granularity=timestamp requires ts_time_col (the UPMT-style time column)",
            )
        cols, err = streaming_service.probe_view_columns(table)
        if cols and ts_time.upper() not in {c.upper() for c in cols}:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"ts_time_col '{ts_time}' not found in view {table.table} (columns probed: {len(cols)})",
            )

    # If the watermark column/kind changes, the old cursor belongs to a different value space → reset
    # it so the next cycle re-initialises from the target's MAX(new column) instead of comparing the
    # new column against a stale cursor.
    marker_changed = (
        ("ts_col" in fields and new_ts_col != ((cfg_existing.ts_col or "").strip() if cfg_existing else ""))
        or ("ts_kind" in fields and fields["ts_kind"] != ((cfg_existing.ts_kind if cfg_existing else "date") or "date"))
    )

    cfg = streaming_service.upsert_config(db, table.table, **fields)
    if marker_changed:
        cfg.last_watermark = None
        cfg.last_watermark_time = None
        db.commit()
        db.refresh(cfg)
    return streaming_service.config_view(cfg, table, pk=streaming_service.effective_pk(db, table, cfg))


@router.get("/status")
def streaming_status(db: Annotated[Session, Depends(get_db)]) -> dict[str, Any]:
    return {
        "loop": streaming_refresher.get_status(),
        "tables": streaming_service.list_config_views(db),
    }


@router.get("/probe/{table_name}")
def probe_columns(table_name: str, db: Annotated[Session, Depends(get_db)]) -> dict[str, Any]:
    """Probe the view's columns (read-only) — used to auto-detect a UPMT-style time column."""
    table = get_table(table_name)
    if table is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown table")
    cols, err = streaming_service.probe_view_columns(table)
    upmt = [c for c in cols if c.upper().endswith("UPMT") or c.upper().endswith("UPMT0")]
    return {"table": table.table, "columns": cols, "upmt_candidates": upmt, "error": err}


@router.post("/run-once/{table_name}", dependencies=[Depends(require_permission("streaming.run_once"))])
def run_once(
    table_name: str,
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    """Run one streaming cycle synchronously (ignores `enabled`) — for manual testing."""
    table = get_table(table_name)
    if table is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown table")
    cfg = streaming_service.get_config(db, table.table)
    if cfg is None:
        cfg = streaming_service.upsert_config(db, table.table)
    return streaming_service.run_cycle(db, cfg, force=True)

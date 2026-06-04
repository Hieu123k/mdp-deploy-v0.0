"""Editable reference lists — the master data behind the dashboard's fixed fields and
dropdowns, so admins can add / edit / delete options without code changes.

Two kinds of lists:
- Business reference lists (domains, sensitivity, source systems, …) — simple value/label.
- ``ora2pg_tables`` — the JDE migration catalog; ``extra`` carries target_table / module /
  ts_col / pk_columns. This list OVERLAYS the static jde_migrate_tables.json catalog: an
  override row edits a base table, a new row adds one, and ``is_active=False`` hides a base
  table (tombstone). The static JSON stays the seed/source-of-truth fallback.

Behavioural enums tied to backend logic (run statuses, migration tools, user roles, …) are
intentionally NOT managed here.
"""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.ora2pg_catalog import MIGRATABLE_TABLES
from app.models.reference import ReferenceOption

# Business reference lists managed by admins. Keyed list_key -> ordered default values.
DEFAULT_LISTS: dict[str, list[str]] = {
    "domains": [
        "master_data", "procurement", "inventory", "production", "quality", "maintenance",
        "asset", "energy", "finance", "sales", "logistics", "iiot", "other",
    ],
    "business_processes": [
        "procure_to_pay", "order_to_cash", "plan_to_produce", "quality_management",
        "maintenance_management", "inventory_management", "asset_management",
        "energy_management", "iiot_monitoring", "other",
    ],
    "source_layers": ["source", "staging", "canonical", "curated_view", "analytical", "external_api", "generated_table"],
    "canonical_statuses": ["source_aligned", "canonical", "curated", "experimental", "deprecated"],
    "site_scopes": ["enterprise", "site", "area", "line", "work_center", "asset", "not_applicable"],
    "sensitivity_levels": ["public", "internal", "confidential", "restricted"],
    "source_systems": ["JDE ERP", "External API", "Manual / Mock Data", "SQL Server", "PostgreSQL", "Other"],
    "owner_departments": ["Procurement", "Finance", "Operations", "Quality", "Maintenance", "IT/OT", "Other"],
    "db_types": ["postgresql", "oracle", "sqlserver"],
}

ORA2PG_LIST_KEY = "ora2pg_tables"

# list_key values an admin is allowed to manage (guards against editing behavioural enums).
MANAGED_LIST_KEYS = set(DEFAULT_LISTS) | {ORA2PG_LIST_KEY}


def seed_reference_options(db: Session) -> None:
    """Idempotently seed the default option for each managed list (business lists from the
    constants above, ``ora2pg_tables`` from the static catalog). Existing rows are left as-is
    so admin edits/additions/deletions survive restarts."""
    existing = {
        (row.list_key, row.value)
        for row in db.scalars(select(ReferenceOption))
    }
    added = False
    for list_key, values in DEFAULT_LISTS.items():
        for order, value in enumerate(values):
            if (list_key, value) in existing:
                continue
            db.add(ReferenceOption(list_key=list_key, value=value, label=value, sort_order=order))
            added = True
    for order, table in enumerate(MIGRATABLE_TABLES):
        if (ORA2PG_LIST_KEY, table.table) in existing:
            continue
        db.add(ReferenceOption(
            list_key=ORA2PG_LIST_KEY,
            value=table.table,
            label=table.label,
            sort_order=order,
            extra={
                "target_table": table.target_table,
                "module": table.module,
                "ts_col": table.ts_col,
                "pk_columns": None,
                "seeded": True,
            },
        ))
        added = True
    if added:
        db.commit()


def list_options(db: Session, list_key: str, *, include_inactive: bool = False) -> list[ReferenceOption]:
    stmt = select(ReferenceOption).where(ReferenceOption.list_key == list_key)
    if not include_inactive:
        stmt = stmt.where(ReferenceOption.is_active.is_(True))
    stmt = stmt.order_by(ReferenceOption.sort_order.asc(), ReferenceOption.value.asc())
    return list(db.scalars(stmt))


def get_option(db: Session, option_id: uuid.UUID) -> ReferenceOption | None:
    return db.get(ReferenceOption, option_id)


def find_by_value(db: Session, list_key: str, value: str) -> ReferenceOption | None:
    return db.scalar(
        select(ReferenceOption).where(
            ReferenceOption.list_key == list_key, ReferenceOption.value == value
        )
    )


def create_option(
    db: Session, list_key: str, *, value: str, label: str | None = None,
    sort_order: int | None = None, extra: dict[str, Any] | None = None,
) -> ReferenceOption:
    # Re-adding a previously soft-deleted value reactivates the existing row (unique per
    # list_key+value), so the startup seed never resurrects it and the value can come back.
    existing = find_by_value(db, list_key, value)
    if existing is not None:
        existing.is_active = True
        if label is not None:
            existing.label = label
        if extra is not None:
            existing.extra = extra
        db.add(existing)
        db.commit()
        db.refresh(existing)
        return existing
    if sort_order is None:
        rows = list_options(db, list_key, include_inactive=True)
        sort_order = (max((o.sort_order for o in rows), default=-1)) + 1
    option = ReferenceOption(
        list_key=list_key, value=value, label=label or value, sort_order=sort_order, extra=extra,
    )
    db.add(option)
    db.commit()
    db.refresh(option)
    return option


def update_option(db: Session, option: ReferenceOption, **fields: Any) -> ReferenceOption:
    for key in ("value", "label", "sort_order", "extra", "is_active"):
        if key in fields and fields[key] is not None:
            setattr(option, key, fields[key])
    db.add(option)
    db.commit()
    db.refresh(option)
    return option


def delete_option(db: Session, option: ReferenceOption) -> None:
    # Soft delete: hides the option from dropdowns but keeps the row, so the idempotent seed
    # does NOT re-create a default that an admin intentionally removed.
    option.is_active = False
    db.add(option)
    db.commit()

"""RBAC capability layer (prompt 34): the fixed permission keys, default per-role grants, an
idempotent seed, lookup for ``require_permission``, and the matrix get/set for the Role tab.

This is the *role → can-do* layer (enforced BE-side, 403). ``admin`` is implicit-full and has NO
rows. Distinct from the per-user *nav visibility* layer (user_preferences)."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.role_permission import RolePermission
from app.schemas.user import USER_ROLES

# Fixed capability keys (grouped, order preserved for the UI grid).
PERMISSION_KEYS: list[str] = [
    "migration.run",
    "migration.verify",
    "migration.repair",
    "streaming.configure",
    "streaming.run_once",
    "data_model.create",
    "data_model.edit",
    "data_model.delete",
    "api_key.create",
    "api_key.delete",
    "connection.manage",
    "db_browser.view",
    "pk.edit",
    "users.manage",
    "role.manage",
]

# These two are ADMIN-ONLY and NEVER grantable to another role (anti-escalation).
ADMIN_ONLY_PERMISSIONS: set[str] = {"users.manage", "role.manage"}

# Default grants seeded once per role (admin = everything, implicit — not stored).
DEFAULT_ROLE_PERMISSIONS: dict[str, set[str]] = {
    "data_engineer": {
        "migration.run",
        "migration.verify",
        "migration.repair",
        "streaming.configure",
        "streaming.run_once",
        "data_model.create",
        "data_model.edit",
        "data_model.delete",
        "pk.edit",
        "db_browser.view",
        "connection.manage",
    },
    "api_manager": {"api_key.create", "api_key.delete", "db_browser.view"},
    "viewer": set(),  # view-only — no action capability
}


def role_has_permission(db: Session, role: str, permission_key: str) -> bool:
    """True if ``role`` may do ``permission_key``. ``admin`` is always full."""
    if role == "admin":
        return True
    row = db.scalar(
        select(RolePermission).where(
            RolePermission.role == role,
            RolePermission.permission_key == permission_key,
        )
    )
    return bool(row and row.allowed)


def get_permission_matrix(db: Session) -> dict:
    """{permission_keys, admin_only, roles:{role:{key:bool}}} for the Role-tab grid. admin = all True."""
    rows = db.scalars(select(RolePermission)).all()
    by = {(r.role, r.permission_key): r.allowed for r in rows}
    roles = {
        role: {
            key: True if role == "admin" else bool(by.get((role, key), False))
            for key in PERMISSION_KEYS
        }
        for role in sorted(USER_ROLES)
    }
    return {
        "permission_keys": PERMISSION_KEYS,
        "admin_only": sorted(ADMIN_ONLY_PERMISSIONS),
        "roles": roles,
    }


def seed_role_permissions(db: Session) -> int:
    """Idempotent: INSERT a row for every missing (non-admin role × permission_key) with its default
    ``allowed`` — NEVER overwrites an existing (admin-edited) value. Returns rows inserted."""
    existing = {(r.role, r.permission_key) for r in db.scalars(select(RolePermission)).all()}
    created = 0
    for role in USER_ROLES:
        if role == "admin":
            continue  # admin implicit-full → no rows
        defaults = DEFAULT_ROLE_PERMISSIONS.get(role, set())
        for key in PERMISSION_KEYS:
            if (role, key) in existing:
                continue
            allowed = key in defaults and key not in ADMIN_ONLY_PERMISSIONS
            db.add(RolePermission(role=role, permission_key=key, allowed=allowed))
            created += 1
    if created:
        db.commit()
    return created


def set_role_permission(db: Session, role: str, permission_key: str, allowed: bool, *, commit: bool = True) -> None:
    """Upsert one grant. Anti-escalation (admin-only keys, admin self-lock) is enforced by the API.
    Pass ``commit=False`` to batch several writes into one atomic transaction (the caller commits)."""
    row = db.scalar(
        select(RolePermission).where(
            RolePermission.role == role,
            RolePermission.permission_key == permission_key,
        )
    )
    if row is None:
        db.add(RolePermission(role=role, permission_key=permission_key, allowed=allowed))
    else:
        row.allowed = allowed
    if commit:
        db.commit()

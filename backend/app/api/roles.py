"""Role → capability matrix API (prompt 34). Admin-only (require_admin == the role.manage holder).

Anti-escalation, enforced here AND mirrored in the UI:
  * ``users.manage`` / ``role.manage`` can NEVER be granted to a role other than admin.
  * The ``admin`` role is implicit-full and NOT editable here — so admin can't lock itself out of
    ``role.manage``/``users.manage``.
"""
from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import require_admin
from app.db.session import get_db
from app.models.user import User
from app.schemas.user import USER_ROLES
from app.services.permission_service import (
    ADMIN_ONLY_PERMISSIONS,
    PERMISSION_KEYS,
    get_permission_matrix,
    set_role_permission,
)

router = APIRouter(
    prefix="/roles",
    tags=["roles"],
    dependencies=[Depends(require_admin)],  # only admin (the role.manage holder) may view/edit
)


class PermissionMatrixUpdate(BaseModel):
    # {role: {permission_key: allowed}}
    roles: dict[str, dict[str, bool]]


@router.get("/permissions")
def get_permissions(db: Annotated[Session, Depends(get_db)]) -> dict[str, Any]:
    return get_permission_matrix(db)


@router.put("/permissions")
def update_permissions(
    payload: PermissionMatrixUpdate,
    db: Annotated[Session, Depends(get_db)],
    _admin: Annotated[User, Depends(require_admin)],
) -> dict[str, Any]:
    # Phase 1 — validate the ENTIRE payload BEFORE mutating anything (atomic: a single bad cell
    # rejects the whole request, never a silent partial apply).
    writes: list[tuple[str, str, bool]] = []
    for role, keys in payload.roles.items():
        if role == "admin":
            continue  # implicit-full + self-lock protection — admin row is never written
        if role not in USER_ROLES:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Unknown role: {role}")
        for key, allowed in keys.items():
            if key not in PERMISSION_KEYS:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Unknown permission: {key}")
            if allowed and key in ADMIN_ONLY_PERMISSIONS:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"'{key}' is admin-only and cannot be granted to role '{role}'",
                )
            writes.append((role, key, allowed))

    # Phase 2 — apply all in one transaction (commit once).
    for role, key, allowed in writes:
        set_role_permission(db, role, key, allowed, commit=False)
    db.commit()
    return get_permission_matrix(db)

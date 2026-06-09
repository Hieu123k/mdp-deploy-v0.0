"""User preferences API — per-user theme (self-service) + admin-controlled tab config (RBAC UX).

- ``/preferences/me`` (any authenticated user): read own prefs; update own theme (and own nav).
- ``/preferences/users/{user_id}`` (admin only, via ``require_role('admin')``): read/set any user's
  nav config (hide / rename / reorder tabs) and theme. The hard security boundary remains
  ``require_role`` on protected routes; nav config is a UX/visibility layer.
"""
from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_admin
from app.db.session import get_db
from app.models.user import User
from app.services import preferences_service
from app.services.user_service import get_user, list_users

router = APIRouter(prefix="/preferences", tags=["preferences"])


class PreferenceUpdate(BaseModel):
    theme: str | None = None
    nav_config: dict[str, Any] | None = None


def _validate_theme(theme: str | None) -> None:
    if theme is not None and theme not in preferences_service.VALID_THEMES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"theme must be one of {sorted(preferences_service.VALID_THEMES)}",
        )


@router.get("/me")
def get_my_preferences(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    pref = preferences_service.get_or_create(db, current_user.id)
    return preferences_service.to_dict(pref)


@router.put("/me")
def update_my_preferences(
    payload: PreferenceUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    """A user updates their OWN theme (and optionally their own nav personalisation)."""
    _validate_theme(payload.theme)
    pref = preferences_service.update(
        db, current_user.id, theme=payload.theme, nav_config=payload.nav_config
    )
    return preferences_service.to_dict(pref)


@router.get("/users", dependencies=[Depends(require_admin)])
def list_user_preferences(db: Annotated[Session, Depends(get_db)]) -> dict[str, Any]:
    """Admin: roster of users + their current prefs (for the Settings tab-config screen)."""
    rows = []
    for u in list_users(db):
        pref = preferences_service.get_or_create(db, u.id)
        rows.append({
            "user_id": str(u.id),
            "username": u.username,
            "role": u.role,
            "is_active": u.is_active,
            "theme": pref.theme,
            "nav_config": pref.nav_config or {},
        })
    return {"users": rows}


@router.get("/users/{user_id}", dependencies=[Depends(require_admin)])
def get_user_preferences(
    user_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    user = get_user(db, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    pref = preferences_service.get_or_create(db, user.id)
    return {"username": user.username, "role": user.role, **preferences_service.to_dict(pref)}


@router.put("/users/{user_id}", dependencies=[Depends(require_admin)])
def set_user_preferences(
    user_id: uuid.UUID,
    payload: PreferenceUpdate,
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    """Admin: set another user's nav config (hide/rename/reorder tabs) and/or theme."""
    user = get_user(db, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    _validate_theme(payload.theme)
    pref = preferences_service.update(
        db, user.id, theme=payload.theme, nav_config=payload.nav_config
    )
    return {"username": user.username, "role": user.role, **preferences_service.to_dict(pref)}

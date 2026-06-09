"""User preferences (theme + per-user nav/RBAC tab config) service."""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.user_preferences import UserPreference

VALID_THEMES = {"light", "dark"}


def get_or_create(db: Session, user_id: uuid.UUID) -> UserPreference:
    pref = db.scalar(select(UserPreference).where(UserPreference.user_id == user_id))
    if pref is None:
        pref = UserPreference(user_id=user_id, theme="light", nav_config=None)
        db.add(pref)
        db.commit()
        db.refresh(pref)
    return pref


def to_dict(pref: UserPreference) -> dict[str, Any]:
    return {
        "user_id": str(pref.user_id),
        "theme": pref.theme,
        "nav_config": pref.nav_config or {},
    }


def update(
    db: Session,
    user_id: uuid.UUID,
    *,
    theme: str | None = None,
    nav_config: dict[str, Any] | None = None,
) -> UserPreference:
    pref = get_or_create(db, user_id)
    if theme is not None:
        pref.theme = theme
    if nav_config is not None:
        # Stored verbatim (FE-controlled overlay keyed by href). Replace wholesale so an admin can
        # also clear an override by sending it without that href.
        pref.nav_config = nav_config
    db.add(pref)
    db.commit()
    db.refresh(pref)
    return pref

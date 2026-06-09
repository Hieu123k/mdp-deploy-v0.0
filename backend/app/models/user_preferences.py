import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Uuid

from app.db.base import Base
from app.models.migration import jsonb_type


class UserPreference(Base):
    """Per-user UI preferences + admin-controlled tab config (Settings / RBAC).

    One row per user:
    - ``theme`` — ``light`` | ``dark`` (the user toggles their own; persisted across reloads).
    - ``nav_config`` — per-tab overrides keyed by route href:
      ``{"/users": {"visible": false, "label": "Accounts", "order": 3}, ...}``.
      An admin edits another user's ``nav_config`` to hide / rename / reorder that user's sidebar
      tabs; the front-end overlays it on the canonical ``NAV_ITEMS``. Hidden tabs are also blocked
      by a client route-guard (role-based BE 403 via ``require_role`` remains the security layer).
    """

    __tablename__ = "user_preferences"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False, index=True
    )
    theme: Mapped[str] = mapped_column(String(20), nullable=False, default="light", server_default="light")
    nav_config: Mapped[dict[str, Any] | None] = mapped_column(jsonb_type, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

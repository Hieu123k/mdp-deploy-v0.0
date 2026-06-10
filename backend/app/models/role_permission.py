import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Uuid

from app.db.base import Base


class RolePermission(Base):
    """Capability granted to a role (prompt 34 RBAC). One row per (role, permission_key); ``allowed``
    toggles it. ``admin`` is implicitly full (never consulted here). This is the *role → can-do*
    layer enforced by ``require_permission`` (BE 403) — distinct from the per-user *nav visibility*
    layer (user_preferences)."""

    __tablename__ = "role_permissions"
    __table_args__ = (UniqueConstraint("role", "permission_key", name="uq_role_permission"),)

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    role: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    permission_key: Mapped[str] = mapped_column(String(100), nullable=False)
    allowed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

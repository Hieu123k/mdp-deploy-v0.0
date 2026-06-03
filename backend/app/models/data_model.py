import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON, Uuid

from app.db.base import Base


jsonb_type = JSON().with_variant(JSONB, "postgresql")


class DataModel(Base):
    __tablename__ = "data_models"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    name: Mapped[str] = mapped_column(String(150), unique=True, index=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    type: Mapped[str] = mapped_column(String(1), nullable=False)
    category: Mapped[str | None] = mapped_column(String(100), nullable=True)
    namespace: Mapped[str | None] = mapped_column(String(255), nullable=True)
    domain: Mapped[str | None] = mapped_column(String(100), nullable=True)
    entity_type: Mapped[str | None] = mapped_column(String(150), nullable=True)
    business_process: Mapped[str | None] = mapped_column(String(100), nullable=True)
    source_layer: Mapped[str | None] = mapped_column(String(100), nullable=True)
    canonical_status: Mapped[str | None] = mapped_column(String(100), nullable=True)
    site_scope: Mapped[str | None] = mapped_column(String(100), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    business_definition: Mapped[str | None] = mapped_column(Text, nullable=True)
    owner_department: Mapped[str | None] = mapped_column(String(150), nullable=True)
    source_system: Mapped[str | None] = mapped_column(String(150), nullable=True)
    primary_key: Mapped[str | None] = mapped_column(String(150), nullable=True)
    generated_table: Mapped[str | None] = mapped_column(String(255), nullable=True)
    attributes: Mapped[list[dict[str, Any]]] = mapped_column(jsonb_type, nullable=False)
    relationships: Mapped[list[dict[str, Any]] | None] = mapped_column(jsonb_type, nullable=True)
    refresh_policy: Mapped[str | None] = mapped_column(String(100), nullable=True)
    sensitivity_level: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="internal",
        server_default="internal",
    )
    ai_enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="true",
    )
    status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="active",
        server_default="active",
    )
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

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON, Uuid

from app.db.base import Base


jsonb_type = JSON().with_variant(JSONB, "postgresql")


class Transaction(Base):
    __tablename__ = "transactions"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    direction: Mapped[str] = mapped_column(String(50), nullable=False)
    protocol: Mapped[str] = mapped_column(String(50), nullable=False)
    data_model_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("data_models.id"),
        nullable=True,
    )
    endpoint: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    request_payload: Mapped[dict[str, Any] | list[Any] | None] = mapped_column(
        jsonb_type,
        nullable=True,
    )
    response_payload: Mapped[dict[str, Any] | list[Any] | None] = mapped_column(
        jsonb_type,
        nullable=True,
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    auth_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    api_key_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("api_keys.id"),
        nullable=True,
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id"),
        nullable=True,
    )
    source_system: Mapped[str | None] = mapped_column(String(150), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

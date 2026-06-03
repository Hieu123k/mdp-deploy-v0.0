import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON, Uuid

from app.db.base import Base


jsonb_type = JSON().with_variant(JSONB, "postgresql")


class Connection(Base):
    __tablename__ = "connections"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(150), unique=True, index=True, nullable=False)
    type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    host: Mapped[str | None] = mapped_column(String(255), nullable=True)
    port: Mapped[int | None] = mapped_column(Integer, nullable=True)
    database_name: Mapped[str | None] = mapped_column(String(150), nullable=True)
    username: Mapped[str | None] = mapped_column(String(150), nullable=True)
    encrypted_password: Mapped[str | None] = mapped_column(Text, nullable=True)
    base_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    mqtt_topic_prefix: Mapped[str | None] = mapped_column(String(255), nullable=True)
    config: Mapped[dict[str, Any] | None] = mapped_column(jsonb_type, nullable=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="active", server_default="active")
    created_by: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    last_test_status: Mapped[str | None] = mapped_column(String(50), nullable=True)
    last_test_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_test_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

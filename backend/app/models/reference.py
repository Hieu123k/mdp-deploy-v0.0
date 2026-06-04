import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON, Uuid

from app.db.base import Base

jsonb_type = JSON().with_variant(JSONB, "postgresql")


class ReferenceOption(Base):
    """A single editable option in a named reference list (e.g. ``domains``,
    ``sensitivity_levels``, ``ora2pg_tables``). Admins manage these via the API so the
    dropdowns / fixed lists in the UI are no longer hard-coded. ``extra`` holds structured
    payload for richer lists (e.g. the ora2pg catalog's target_table/module/ts_col/pk).
    """

    __tablename__ = "reference_options"
    __table_args__ = (UniqueConstraint("list_key", "value", name="uq_reference_options_list_value"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    list_key: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    value: Mapped[str] = mapped_column(String(255), nullable=False)
    label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    extra: Mapped[dict[str, Any] | None] = mapped_column(jsonb_type, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

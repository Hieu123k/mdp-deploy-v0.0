import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Uuid

from app.db.base import Base
from app.models.migration import jsonb_type


class StreamingConfig(Base):
    """Per-table streaming (watermark-incremental) configuration + cursor.

    One row per migratable Oracle view. The background ``StreamingRefresher`` polls every
    ``enabled`` row and upserts only the source rows whose change-key (``ts_col``, a JDE
    ``UPMJ`` Julian update-date) advanced past the stored cursor — using ora2pg
    ``INSERT … ON CONFLICT DO NOTHING`` against the target PK (idempotent, never duplicates).

    ``granularity``:
    - ``day`` (default, prod-safe) — filter ``ts_col >= cursor - lookback`` on the Julian day.
    - ``timestamp`` (finer, only valid when ``ts_time_col`` exists in the view) — composite
      ``(ts_col > d) OR (ts_col = d AND ts_time_col >= t)``.

    The cursor (``last_watermark`` [+ ``last_watermark_time``]) is stored here so streaming is
    self-contained and does not depend on a ``MigrationJob`` registry row existing.
    """

    __tablename__ = "streaming_configs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_view: Mapped[str] = mapped_column(String(150), unique=True, index=True, nullable=False)
    target_table: Mapped[str | None] = mapped_column(String(150), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    ts_col: Mapped[str | None] = mapped_column(String(150), nullable=True)  # e.g. GLUPMJ (Julian day); None = full-reload
    ts_time_col: Mapped[str | None] = mapped_column(String(150), nullable=True)  # e.g. GLUPMT (time-of-day)
    # Watermark kind: 'date' (Julian CYYDDD → >= cursor-lookback, dedup) or 'sequence' (monotonic id
    # like ILUKID → strict > cursor, no lookback). Julian dates and UKIDs are both NUMBER in Oracle,
    # so the operator picks the kind explicitly — it can't be auto-detected from the column type.
    ts_kind: Mapped[str] = mapped_column(String(20), nullable=False, default="date", server_default="date")
    granularity: Mapped[str] = mapped_column(String(20), nullable=False, default="day", server_default="day")
    poll_interval_sec: Mapped[int] = mapped_column(Integer, nullable=False, default=300, server_default="300")
    lookback_days: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    primary_key_columns: Mapped[list[str] | None] = mapped_column(jsonb_type, nullable=True)
    # Cursor (high-watermark of what has already been pulled). Stored as text to match
    # MigrationJob.last_successful_watermark and to stay numeric-agnostic.
    last_watermark: Mapped[str | None] = mapped_column(String(150), nullable=True)
    last_watermark_time: Mapped[str | None] = mapped_column(String(150), nullable=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_rows_added: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_status: Mapped[str | None] = mapped_column(String(20), nullable=True)  # ok | error | skipped
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    config: Mapped[dict[str, Any] | None] = mapped_column(jsonb_type, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

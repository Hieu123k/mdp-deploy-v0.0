import uuid
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import Uuid

from app.db.base import Base


class Ora2pgSourceCount(Base):
    """Cached source-row count for each migratable Oracle view, refreshed in the background so
    the Migration dashboard's `Source` column is populated for every table on page load —
    without querying Oracle per request.

    `count_mode` = ``estimate`` (cheap, periodic, from Oracle table stats — flagged
    ``approximate``) or ``exact`` (on-demand COUNT(*) via the Verify button). On a failed
    refresh the previous count is kept and ``status`` is set to ``stale`` (never crashes).
    """

    __tablename__ = "ora2pg_source_counts"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_view: Mapped[str] = mapped_column(String(150), unique=True, index=True, nullable=False)
    target_table: Mapped[str | None] = mapped_column(String(150), nullable=True)
    source_row_count: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    count_mode: Mapped[str | None] = mapped_column(String(20), nullable=True)  # estimate | exact
    approximate: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="ok", server_default="ok")  # ok|stale|error
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    counted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

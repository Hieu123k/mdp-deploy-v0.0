import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class TransactionStats(BaseModel):
    """All-time transaction counts grouped by status (no row cap). Powers the Dashboard cards."""

    total: int
    by_status: dict[str, int]


class TransactionRead(BaseModel):
    id: uuid.UUID
    direction: str
    protocol: str
    data_model_id: uuid.UUID | None
    endpoint: str | None
    status: str
    request_payload: dict[str, Any] | list[Any] | None
    response_payload: dict[str, Any] | list[Any] | None
    error_message: str | None
    auth_type: str | None
    api_key_id: uuid.UUID | None
    user_id: uuid.UUID | None
    source_system: str | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class InboundResponse(BaseModel):
    status: str
    model: str
    record_id: uuid.UUID
    message: str

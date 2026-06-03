import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


Direction = Literal["inbound", "outbound"]


class ApiKeyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    description: str | None = None
    source_system: str | None = Field(default=None, max_length=150)
    allowed_directions: list[Direction] = Field(min_length=1)
    allowed_models: list[str] | None = None
    expires_at: datetime | None = None

    @field_validator("allowed_models")
    @classmethod
    def normalize_models(cls, value: list[str] | None) -> list[str] | None:
        return value or None


class ApiKeyUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=150)
    description: str | None = None
    source_system: str | None = Field(default=None, max_length=150)
    allowed_directions: list[Direction] | None = Field(default=None, min_length=1)
    allowed_models: list[str] | None = None
    is_active: bool | None = None
    expires_at: datetime | None = None


class ApiKeyRead(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    key_prefix: str
    source_system: str | None
    allowed_directions: list[str]
    allowed_models: list[str] | None
    is_active: bool
    expires_at: datetime | None
    created_by: uuid.UUID | None
    created_at: datetime
    updated_at: datetime
    last_used_at: datetime | None

    model_config = ConfigDict(from_attributes=True)


class ApiKeyCreateResponse(ApiKeyRead):
    api_key: str

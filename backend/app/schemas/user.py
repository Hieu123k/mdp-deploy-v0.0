import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


def validate_email_like(value: str) -> str:
    if "@" not in value or value.startswith("@") or value.endswith("@"):
        raise ValueError("Email must contain a local part and domain")
    return value


class UserCreate(BaseModel):
    username: str = Field(min_length=1, max_length=150)
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=6, max_length=128)
    full_name: str | None = Field(default=None, max_length=255)
    role: str = Field(default="admin", max_length=50)
    is_active: bool = True

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        return validate_email_like(value)


class UserRead(BaseModel):
    id: uuid.UUID
    username: str
    email: str
    full_name: str | None
    role: str
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class UserUpdate(BaseModel):
    username: str | None = Field(default=None, min_length=1, max_length=150)
    email: str | None = Field(default=None, min_length=3, max_length=255)
    password: str | None = Field(default=None, min_length=6, max_length=128)
    full_name: str | None = Field(default=None, max_length=255)
    role: str | None = Field(default=None, max_length=50)
    is_active: bool | None = None

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str | None) -> str | None:
        return validate_email_like(value) if value is not None else value


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"

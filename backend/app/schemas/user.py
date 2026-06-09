import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


# Roles recognised by RBAC (mirrors USER_ROLES on the front-end + the require_role checks).
USER_ROLES = {"admin", "data_engineer", "api_manager", "viewer"}


def validate_email_like(value: str) -> str:
    if "@" not in value or value.startswith("@") or value.endswith("@"):
        raise ValueError("Email must contain a local part and domain")
    return value


def validate_role(value: str) -> str:
    if value not in USER_ROLES:
        raise ValueError(f"role must be one of {sorted(USER_ROLES)}")
    return value


class UserCreate(BaseModel):
    username: str = Field(min_length=1, max_length=150)
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=6, max_length=128)
    full_name: str | None = Field(default=None, max_length=255)
    # Least-privilege default: omitting role must NOT silently mint an admin. Admin is granted
    # explicitly (seed_default_admin / an admin choosing it in the UI).
    role: str = Field(default="viewer", max_length=50)
    is_active: bool = True

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        return validate_email_like(value)

    @field_validator("role")
    @classmethod
    def _validate_role(cls, value: str) -> str:
        return validate_role(value)


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

    @field_validator("role")
    @classmethod
    def _validate_role(cls, value: str | None) -> str | None:
        return validate_role(value) if value is not None else value


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator


ConnectionType = Literal["postgresql", "oracle", "sqlserver", "rest_api", "mqtt"]
ConnectionStatus = Literal["active", "inactive"]
DATABASE_CONNECTION_TYPES = {"postgresql", "oracle", "sqlserver"}


class ConnectionBase(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    type: ConnectionType
    description: str | None = None
    host: str | None = Field(default=None, max_length=255)
    port: int | None = Field(default=None, ge=1, le=65535)
    database_name: str | None = Field(default=None, max_length=150)
    username: str | None = Field(default=None, max_length=150)
    base_url: HttpUrl | None = None
    mqtt_topic_prefix: str | None = Field(default=None, max_length=255)
    config: dict[str, Any] | None = None
    status: ConnectionStatus = "active"

    @model_validator(mode="after")
    def validate_required_fields(self) -> "ConnectionBase":
        if self.type in {"postgresql", "sqlserver"}:
            missing = [
                field
                for field in ("host", "port", "database_name", "username")
                if getattr(self, field) in (None, "")
            ]
            if missing:
                raise ValueError(
                    f"{self.type} connections require: {', '.join(missing)}"
                )
        if self.type == "oracle":
            config = self.config if isinstance(self.config, dict) else {}
            mode = str(config.get("oracle_connect_mode") or "service_name").lower()
            if mode not in {"service_name", "sid", "dsn"}:
                raise ValueError(
                    "oracle config oracle_connect_mode must be one of: service_name, sid, dsn"
                )
            missing = [
                field
                for field in ("username",)
                if getattr(self, field) in (None, "")
            ]
            if mode == "dsn":
                if not config.get("dsn"):
                    missing.append("config.dsn")
            else:
                for field in ("host", "port"):
                    if getattr(self, field) in (None, ""):
                        missing.append(field)
                if mode == "service_name" and not (
                    config.get("service_name") or self.database_name
                ):
                    missing.append("service_name or database_name")
                if mode == "sid" and not (config.get("sid") or self.database_name):
                    missing.append("sid or database_name")
            if missing:
                raise ValueError(f"oracle connections require: {', '.join(missing)}")
        if self.type == "rest_api" and self.base_url is None:
            raise ValueError("rest_api connections require base_url")
        if self.type == "mqtt":
            missing = [
                field
                for field in ("host", "port")
                if getattr(self, field) in (None, "")
            ]
            if missing:
                raise ValueError(f"mqtt connections require: {', '.join(missing)}")
        return self


class ConnectionCreate(ConnectionBase):
    password: str | None = Field(default=None, max_length=500)


class ConnectionUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=150)
    type: ConnectionType | None = None
    description: str | None = None
    host: str | None = Field(default=None, max_length=255)
    port: int | None = Field(default=None, ge=1, le=65535)
    database_name: str | None = Field(default=None, max_length=150)
    username: str | None = Field(default=None, max_length=150)
    password: str | None = Field(default=None, max_length=500)
    base_url: HttpUrl | None = None
    mqtt_topic_prefix: str | None = Field(default=None, max_length=255)
    config: dict[str, Any] | None = None
    status: ConnectionStatus | None = None


class ConnectionRead(ConnectionBase):
    id: uuid.UUID
    created_by: uuid.UUID | None
    created_at: datetime
    updated_at: datetime
    last_test_status: str | None
    last_test_message: str | None
    last_test_at: datetime | None

    model_config = ConfigDict(from_attributes=True)


class ConnectionTestResponse(BaseModel):
    id: uuid.UUID
    status: str
    message: str
    tested_at: datetime

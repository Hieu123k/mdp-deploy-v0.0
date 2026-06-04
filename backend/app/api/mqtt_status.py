"""MQTT consumer status — a light read-only endpoint for the dashboard indicator."""
from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends

from app.api.deps import get_current_user
from app.core.config import settings
from app.models.user import User
from app.services.mqtt_consumer import get_status

router = APIRouter(prefix="/mqtt", tags=["mqtt"], dependencies=[Depends(get_current_user)])


@router.get("/status")
def mqtt_status(_: Annotated[User, Depends(get_current_user)]) -> dict[str, Any]:
    status = get_status()
    status["configured_enabled"] = settings.mqtt_enabled
    status["configured_broker"] = (
        f"{settings.mqtt_broker_host}:{settings.mqtt_broker_port}" if settings.mqtt_broker_host else None
    )
    status["configured_topics"] = settings.mqtt_topic_list
    return status

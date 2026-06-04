"""MQTT consumer — subscribes to the UNS broker and ingests each message into its Type A
data model by REUSING the HTTP inbound pipeline (`receive_inbound_payload`).

Additive & isolated: enabled only when ``MQTT_ENABLED`` is true (default OFF), runs as a single
background task in the FastAPI lifespan, never touches the broker beyond subscribing, and every
bad message is logged & skipped so the subscriber never crashes. The consumer is a trusted
internal client, so it bypasses API-key scope (the scope check lives in the HTTP route, not in
`receive_inbound_payload`) while still writing a Transaction tagged ``source=mqtt`` + topic.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any

from app.core.config import settings
from app.db.session import SessionLocal, engine
from app.services.api_key_service import AuthContext
from app.services.inbound_service import InboundValidationError, receive_inbound_payload

logger = logging.getLogger("mdp.mqtt")

# Trusted internal identity for MQTT-sourced ingests (no API key required).
MQTT_AUTH = AuthContext(auth_type="mqtt", source_system="mqtt")

# Fixed key for the postgres advisory lock that keeps exactly ONE subscriber across workers.
_SINGLETON_LOCK_KEY = 0x4D445154  # "MDQT"

# Live status surfaced to the dashboard (in-memory; one process holds the subscriber).
_status: dict[str, Any] = {
    "enabled": False,
    "connected": False,
    "broker": None,
    "topics": [],
    "messages_received": 0,
    "messages_ingested": 0,
    "messages_skipped": 0,
    "last_message_at": None,
    "last_topic": None,
    "last_error": None,
}


def get_status() -> dict[str, Any]:
    return dict(_status)


def derive_model_name(topic: str, override: dict[str, str] | None = None) -> str:
    """Topic -> model. Default = the last topic segment (mirrors the old Node-RED
    ``object_type = parts[last]``); an explicit override map wins when present."""
    topic = str(topic)
    if override and topic in override:
        return override[topic]
    return topic.rstrip("/").split("/")[-1]


def process_message(db, topic: str, payload: bytes | str) -> dict[str, Any]:
    """Ingest one MQTT message into its Type A model. NEVER raises — returns a result dict
    so the subscriber loop can keep going on any bad message."""
    raw = payload.decode("utf-8", "replace") if isinstance(payload, (bytes, bytearray)) else str(payload)
    try:
        data = json.loads(raw)
    except Exception as exc:
        return {"status": "skipped", "reason": f"invalid JSON: {exc}", "topic": topic}
    if not isinstance(data, dict):
        return {"status": "skipped", "reason": "payload is not a JSON object", "topic": topic}

    model_name = derive_model_name(topic, settings.mqtt_model_map_dict)
    try:
        receive_inbound_payload(
            db,
            model_name=model_name,
            payload=data,
            endpoint=f"mqtt:{topic}",
            auth_context=MQTT_AUTH,
        )
        return {"status": "ingested", "model": model_name, "topic": topic}
    except LookupError:
        return {"status": "skipped", "reason": f"unknown model '{model_name}'", "topic": topic}
    except InboundValidationError as exc:
        return {"status": "skipped", "reason": "validation failed", "errors": exc.errors, "topic": topic}
    except Exception as exc:  # never let one bad message kill the subscriber
        return {"status": "skipped", "reason": f"{exc.__class__.__name__}: {exc}", "topic": topic}


def _record(result: dict[str, Any]) -> None:
    _status["messages_received"] += 1
    _status["last_message_at"] = datetime.now(timezone.utc).isoformat()
    _status["last_topic"] = result.get("topic")
    if result.get("status") == "ingested":
        _status["messages_ingested"] += 1
    else:
        _status["messages_skipped"] += 1
        logger.warning("MQTT message skipped: %s", result.get("reason"))


def _acquire_singleton() -> Any | None:
    """Hold a postgres advisory lock so only one process subscribes (multi-worker safe).
    Returns the held raw connection (keep it open), or None when no lock is needed/possible
    (non-postgres or error) — in which case we proceed assuming a single process. Returns the
    string ``"taken"`` when another process already holds it (caller should NOT subscribe)."""
    try:
        if engine.dialect.name != "postgresql":
            return None
        conn = engine.raw_connection()
        cur = conn.cursor()
        cur.execute("SELECT pg_try_advisory_lock(%s)", (_SINGLETON_LOCK_KEY,))
        got = cur.fetchone()[0]
        cur.close()
        if got:
            return conn  # keep open to hold the lock for the app's lifetime
        conn.close()
        return "taken"
    except Exception:
        return None


async def run_consumer(stop_event: asyncio.Event) -> None:
    """Subscribe and ingest until stopped, reconnecting on any failure."""
    import aiomqtt

    _status.update(
        enabled=True,
        broker=f"{settings.mqtt_broker_host}:{settings.mqtt_broker_port}",
        topics=settings.mqtt_topic_list,
    )
    while not stop_event.is_set():
        try:
            client_kwargs: dict[str, Any] = {
                "hostname": settings.mqtt_broker_host,
                "port": settings.mqtt_broker_port,
                "identifier": settings.mqtt_client_id,
            }
            if settings.mqtt_username:
                client_kwargs["username"] = settings.mqtt_username
                client_kwargs["password"] = settings.mqtt_password or None
            if settings.mqtt_tls:
                import ssl

                client_kwargs["tls_context"] = ssl.create_default_context()

            async with aiomqtt.Client(**client_kwargs) as client:
                for topic in settings.mqtt_topic_list:
                    await client.subscribe(topic, qos=settings.mqtt_qos)
                _status.update(connected=True, last_error=None)
                logger.info("MQTT connected to %s, subscribed: %s", _status["broker"], _status["topics"])
                async for message in client.messages:
                    if stop_event.is_set():
                        break
                    try:
                        with SessionLocal() as db:
                            result = process_message(db, str(message.topic), message.payload)
                    except Exception as exc:  # session-level safety net
                        result = {"status": "skipped", "reason": f"session error: {exc}", "topic": str(message.topic)}
                    _record(result)
        except asyncio.CancelledError:
            break
        except Exception as exc:
            _status.update(connected=False, last_error=str(exc))
            logger.warning("MQTT connection error (%s); reconnecting in %ss", exc, settings.mqtt_reconnect_seconds)
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=settings.mqtt_reconnect_seconds)
            except asyncio.TimeoutError:
                pass
    _status.update(connected=False)


class MqttConsumerHandle:
    """Owns the background task + the singleton lock; created/torn down by the lifespan."""

    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()
        self._lock_conn: Any | None = None

    def start(self) -> bool:
        if not settings.mqtt_enabled:
            return False
        lock = _acquire_singleton()
        if lock == "taken":
            logger.info("MQTT consumer not started in this process (singleton lock held elsewhere)")
            return False
        self._lock_conn = lock if lock not in (None, "taken") else None
        self._task = asyncio.create_task(run_consumer(self._stop))
        return True

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
        if self._lock_conn is not None:
            try:
                self._lock_conn.close()
            except Exception:
                pass
        _status.update(enabled=False, connected=False)

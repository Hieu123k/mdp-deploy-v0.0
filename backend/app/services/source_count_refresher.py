"""Background refresher that periodically fills the source-count cache with ESTIMATE counts.

Runs as a FastAPI lifespan task. Enabled only when ``ORA2PG_SOURCE_COUNT_ENABLED`` is true
(default OFF — only on .63 where Oracle is reachable). A postgres advisory lock guarantees a
single refresher across uvicorn workers. The loop NEVER does exact COUNT(*) (that is on-demand
via Verify) — it only reads Oracle stats, so it never loads the 30M tables.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.core.config import settings
from app.core.ora2pg_catalog import MIGRATABLE_TABLES
from app.db.session import SessionLocal, engine
from app.services.source_count_service import refresh_estimates

logger = logging.getLogger("mdp.source_count")

_SINGLETON_LOCK_KEY = 0x53524343  # "SRCC"

_status: dict[str, Any] = {"enabled": False, "running": False, "last_cycle": None, "last_result": None}


def get_status() -> dict[str, Any]:
    return dict(_status)


def _acquire_singleton() -> Any | None:
    """Hold a postgres advisory lock so only one process refreshes. Returns the held raw
    connection (keep open), ``"taken"`` if another process holds it, or None (non-postgres /
    error → proceed assuming a single process)."""
    try:
        if engine.dialect.name != "postgresql":
            return None
        conn = engine.raw_connection()
        cur = conn.cursor()
        cur.execute("SELECT pg_try_advisory_lock(%s)", (_SINGLETON_LOCK_KEY,))
        got = cur.fetchone()[0]
        cur.close()
        if got:
            return conn
        conn.close()
        return "taken"
    except Exception:
        return None


async def _loop(stop_event: asyncio.Event) -> None:
    _status.update(enabled=True, running=True)
    interval = max(30, int(settings.ora2pg_source_count_interval or 300))
    while not stop_event.is_set():
        try:
            with SessionLocal() as db:
                result = refresh_estimates(db, MIGRATABLE_TABLES)
            _status.update(last_result=result)
            logger.info("source-count estimate cycle: %s", result)
        except Exception as exc:  # pragma: no cover - the cycle must never kill the task
            _status.update(last_result={"error": str(exc)})
            logger.warning("source-count cycle failed: %s", exc)
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval)
        except asyncio.TimeoutError:
            pass
    _status.update(running=False)


class SourceCountRefresher:
    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()
        self._lock_conn: Any | None = None

    def start(self) -> bool:
        if not settings.ora2pg_source_count_enabled:
            return False
        lock = _acquire_singleton()
        if lock == "taken":
            logger.info("source-count refresher not started (singleton lock held elsewhere)")
            return False
        self._lock_conn = lock if lock not in (None, "taken") else None
        self._task = asyncio.create_task(_loop(self._stop))
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
        _status.update(enabled=False, running=False)

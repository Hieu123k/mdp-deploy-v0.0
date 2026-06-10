"""Background streaming poll-loop: every ``streaming_interval`` seconds, run a watermark-
incremental cycle for each enabled ``streaming_config`` table that is due.

Mirrors ``source_count_refresher`` exactly (FastAPI lifespan task + a postgres advisory lock so
only ONE loop runs across uvicorn workers). Enabled only when ``STREAMING_ENABLED`` is true
(default OFF). A failing cycle is caught and logged — it never kills the task. ``stop()`` cancels
cleanly and releases the lock.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.core.config import settings
from app.db.session import SessionLocal, engine
from app.services import streaming_service

logger = logging.getLogger("mdp.streaming")

# Distinct from the source-count refresher lock (0x53524343 "SRCC") so the two singletons
# never collide. 0x53545257 = "STRW" (STReaming Watermark).
_SINGLETON_LOCK_KEY = 0x53545257

_status: dict[str, Any] = {"enabled": False, "running": False, "last_cycle": None, "last_result": None}


def get_status() -> dict[str, Any]:
    return dict(_status)


def _acquire_singleton() -> Any | None:
    """Hold a postgres advisory lock so only one process streams. Returns the held raw connection
    (keep open), ``"taken"`` if another process holds it, or None (non-postgres / error → proceed
    assuming a single process)."""
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


def _run_all_due_blocking() -> dict[str, Any]:
    """Synchronous cycle (opens its own session). Run via run_in_executor so a long ora2pg pull /
    full-reload (F4111 ~58M can take 1h+) executes on a worker THREAD and never blocks the asyncio
    event loop — /health and every other request stay responsive (the deferred report-27 #5 fix)."""
    with SessionLocal() as db:
        return streaming_service.run_all_due(db)


async def _loop(stop_event: asyncio.Event) -> None:
    _status.update(running=True)
    # Idle tick (no enabled table): how often to re-check if a table got enabled.
    idle_interval = max(2, int(settings.streaming_interval or 60))
    while not stop_event.is_set():
        interval = idle_interval
        try:
            # Master kill-switch (default ON): only skip work if ops explicitly disabled streaming.
            # Otherwise the per-table `enabled` flag (run_all_due) is the sole control.
            _status.update(enabled=bool(settings.streaming_enabled))
            if settings.streaming_enabled:
                # Offload the blocking cycle to a thread (executor) — never run ora2pg in the loop.
                result = await asyncio.get_running_loop().run_in_executor(None, _run_all_due_blocking)
                _status.update(last_result=result)
                if result.get("ran"):
                    logger.info("streaming poll cycle: %s", result)
                # The loop sleeps exactly the smallest enabled per-table interval → the Settings
                # "Interval (s)" value is the single, real cadence (no fixed 60s tick on top).
                nxt = result.get("next_interval")
                if nxt:
                    interval = max(2, int(nxt))
        except Exception as exc:  # pragma: no cover - the cycle must never kill the task
            _status.update(last_result={"error": str(exc)})
            logger.warning("streaming poll cycle failed: %s", exc)
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval)
        except asyncio.TimeoutError:
            pass
    _status.update(running=False)


class StreamingRefresher:
    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()
        self._lock_conn: Any | None = None

    def start(self) -> bool:
        # The loop ALWAYS starts (singleton via advisory lock); the per-table `enabled` flag is the
        # control — toggling a table on the Settings UI is enough to start auto-migration, no env
        # flip / restart needed. `STREAMING_ENABLED` is now only a master kill-switch (default ON,
        # re-checked each tick) for ops to globally pause; an idle loop (no enabled table) is near-free.
        lock = _acquire_singleton()
        if lock == "taken":
            logger.info("streaming refresher not started (singleton lock held elsewhere)")
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

"""Streaming (watermark-incremental) tests.

Unit-tests the pure predicate/granularity logic and the auth-gated config/status/run-once API.
The live idempotent upsert (INSERT ON CONFLICT DO NOTHING) needs real Oracle + the ora2pg
container, so it is exercised in the on-VM demo (report 27), not here — but the predicate
*stability* that underpins idempotency (same cursor → same WHERE) is asserted below.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.services.streaming_service import (
    build_streaming_predicate,
    effective_granularity,
)


# --- pure predicate / granularity logic ------------------------------------------------------

def test_predicate_day_subtracts_lookback() -> None:
    p = build_streaming_predicate(
        "V2_PRO_F0911", "GLUPMJ", granularity="day", cursor_day="124100", lookback_days=1
    )
    assert p == "V2_PRO_F0911[GLUPMJ >= 124099]"


def test_predicate_day_zero_lookback() -> None:
    p = build_streaming_predicate(
        "v2_pro_f0911", "glupmj", granularity="day", cursor_day="124100", lookback_days=0
    )
    # view + column are upper-cased for the ora2pg WHERE directive
    assert p == "V2_PRO_F0911[GLUPMJ >= 124100]"


def test_predicate_day_null_cursor_defaults_to_zero() -> None:
    p = build_streaming_predicate("V2_PRO_F0911", "GLUPMJ", granularity="day", cursor_day=None)
    assert p == "V2_PRO_F0911[GLUPMJ >= 0]"


def test_predicate_timestamp_composite() -> None:
    p = build_streaming_predicate(
        "V2_PRO_F0911",
        "GLUPMJ",
        ts_time_col="GLUPMT",
        granularity="timestamp",
        cursor_day="124100",
        cursor_time="3000",
    )
    assert p == "V2_PRO_F0911[(GLUPMJ > 124100) OR (GLUPMJ = 124100 AND GLUPMT >= 3000)]"


def test_predicate_timestamp_falls_back_to_day_without_time_col() -> None:
    # granularity=timestamp but no ts_time_col → locked to day (prod-safe)
    p = build_streaming_predicate(
        "V2_PRO_F0911", "GLUPMJ", granularity="timestamp", cursor_day="124100", lookback_days=1
    )
    assert p == "V2_PRO_F0911[GLUPMJ >= 124099]"


def test_predicate_is_stable_for_same_cursor() -> None:
    # Stability underpins idempotency: re-running the same cycle re-pulls the same range,
    # which ON CONFLICT DO NOTHING then dedups.
    args = dict(granularity="day", cursor_day="124100", lookback_days=1)
    assert build_streaming_predicate("V2_PRO_F0911", "GLUPMJ", **args) == build_streaming_predicate(
        "V2_PRO_F0911", "GLUPMJ", **args
    )


def test_effective_granularity_gate() -> None:
    assert effective_granularity("timestamp", "GLUPMT") == "timestamp"
    assert effective_granularity("timestamp", None) == "day"  # no time col → locked to day
    assert effective_granularity("day", "GLUPMT") == "day"
    assert effective_granularity("bogus", None) == "day"


# --- API (auth-gated) ------------------------------------------------------------------------

def test_streaming_config_requires_auth(client: TestClient) -> None:
    assert client.get("/streaming/config").status_code == 401


def test_list_config_returns_catalog_defaults(client: TestClient, auth_headers: dict[str, str]) -> None:
    r = client.get("/streaming/config", headers=auth_headers)
    assert r.status_code == 200
    tables = r.json()["tables"]
    assert len(tables) >= 1
    f0911 = next((t for t in tables if t["source_view"].upper() == "V2_PRO_F0911"), None)
    assert f0911 is not None
    assert f0911["enabled"] is False  # default OFF
    assert f0911["granularity"] == "day"  # default granularity


def test_put_config_enable_and_set_ts_col(client: TestClient, auth_headers: dict[str, str]) -> None:
    r = client.put(
        "/streaming/config/V2_PRO_F0911",
        headers=auth_headers,
        json={"enabled": True, "ts_col": "GLUPMJ", "lookback_days": 2, "poll_interval_sec": 120},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["enabled"] is True
    assert body["ts_col"] == "GLUPMJ"
    assert body["lookback_days"] == 2
    assert body["poll_interval_sec"] == 120


def test_put_config_rejects_bad_granularity(client: TestClient, auth_headers: dict[str, str]) -> None:
    r = client.put("/streaming/config/V2_PRO_F0911", headers=auth_headers, json={"granularity": "weekly"})
    assert r.status_code == 400


def test_put_config_timestamp_requires_time_col(client: TestClient, auth_headers: dict[str, str]) -> None:
    # granularity=timestamp without ts_time_col must be rejected (would silently fall back to day)
    r = client.put("/streaming/config/V2_PRO_F0911", headers=auth_headers, json={"granularity": "timestamp"})
    assert r.status_code == 400


def test_put_config_unknown_table_404(client: TestClient, auth_headers: dict[str, str]) -> None:
    r = client.put("/streaming/config/NOT_A_TABLE", headers=auth_headers, json={"enabled": True})
    assert r.status_code == 404


def test_status_shape(client: TestClient, auth_headers: dict[str, str]) -> None:
    r = client.get("/streaming/status", headers=auth_headers)
    assert r.status_code == 200
    body = r.json()
    assert "loop" in body and "tables" in body
    # `enabled` reflects the master kill-switch (default ON); the per-table `enabled` flag is what
    # actually drives migration. The loop task itself isn't started by the test harness lifespan.
    assert isinstance(body["loop"]["enabled"], bool)
    assert isinstance(body["loop"]["running"], bool)


def test_run_once_is_graceful_without_oracle(client: TestClient, auth_headers: dict[str, str]) -> None:
    # No Oracle / no ora2pg container → the cycle returns a clean error, never a 500.
    # Env-sensitive: with no ts_col configured, F0911 now runs Case-B full-reload (prompt 35). On an
    # Oracle-capable host (mdp2 / tipa-mdp during deploy) that reload genuinely SUCCEEDS (ok=True) —
    # correct behaviour, not a failure — so we only assert the graceful-error contract when Oracle is
    # unreachable. Either way the response must be 200 (never 500).
    r = client.post("/streaming/run-once/V2_PRO_F0911", headers=auth_headers)
    assert r.status_code == 200
    body = r.json()
    if body["ok"]:
        pytest.skip("Oracle reachable — full-reload succeeded; the no-Oracle contract does not apply")
    assert body["ok"] is False
    assert body["error"]  # a clear message (target missing / oracle unreachable)


# --- report-29 behaviour: per-table enable = the control; single cadence (no 30s floor / 60s tick) ---

def test_report29_master_kill_switch_default_on() -> None:
    """STREAMING_ENABLED is now a MASTER kill-switch that defaults ON (the loop always runs and the
    per-table `enabled` flag is the real control)."""
    from app.core.config import Settings

    assert Settings.model_fields["streaming_enabled"].default is True


def test_report29_single_cadence_floor() -> None:
    """The per-table `poll_interval_sec` ("Run every (s)") is the one cadence, honoured down to a
    small absolute floor — no separate 30s floor or fixed 60s loop tick."""
    from app.services.streaming_service import MIN_INTERVAL, run_all_due

    assert MIN_INTERVAL == 2
    assert callable(run_all_due)

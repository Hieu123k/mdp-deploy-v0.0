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
    config_view,
    effective_granularity,
    is_full_reload,
    upsert_key_for,
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


# --- upsert-key rule (prompt 36): PK / sequence-marker-as-key / date-no-PK → full ---------------

def test_upsert_key_prefers_real_pk() -> None:
    # A real PK is always the key, marker kind notwithstanding.
    assert upsert_key_for("UPMJ", False, ["gldoc", "glkco"]) == ["gldoc", "glkco"]
    assert upsert_key_for("ILUKID", True, ["ilukid"]) == ["ilukid"]


def test_upsert_key_sequence_marker_is_its_own_key() -> None:
    # No PK + a sequence/id marker → the marker itself is the ON CONFLICT key (F4111 ILUKID).
    assert upsert_key_for("ILUKID", True, None) == ["ILUKID"]


def test_upsert_key_date_no_pk_has_no_key() -> None:
    # No PK + a date marker (not unique) → no key → must full-reload (Case B).
    assert upsert_key_for("UPMJ", False, None) is None
    # No marker at all → no key.
    assert upsert_key_for(None, True, None) is None


def _cfg(**kw):
    from app.models.streaming_config import StreamingConfig

    return StreamingConfig(source_view="V2_PRO_F4111", target_table="v2_pro_f4111", **kw)


def test_is_full_reload_rules() -> None:
    assert is_full_reload(_cfg(ts_col=None)) is True                                   # no marker → full
    assert is_full_reload(_cfg(ts_col="ILUKID", ts_kind="sequence")) is False          # seq marker-as-key
    assert is_full_reload(_cfg(ts_col="UPMJ", ts_kind="date")) is True                 # date + no PK → full
    assert is_full_reload(_cfg(ts_col="UPMJ", ts_kind="date", primary_key_columns=["x"])) is False  # date + PK


def test_config_view_effective_upsert_key() -> None:
    from app.core.ora2pg_catalog import get_table

    table = get_table("V2_PRO_F4111")
    assert table is not None
    # sequence marker, no PK → the marker is the key, mode incremental.
    v = config_view(_cfg(ts_col="ILUKID", ts_kind="sequence"), table, pk=None)
    assert v["effective_upsert_key"] == ["ILUKID"]
    assert v["upsert_key_kind"] == "marker"
    assert v["mode"] == "incremental"
    # date marker, no PK → no key, mode full.
    v2 = config_view(_cfg(ts_col="UPMJ", ts_kind="date"), table, pk=None)
    assert v2["effective_upsert_key"] is None
    assert v2["mode"] == "full"
    # real PK wins → key is the PK, kind primary_key.
    v3 = config_view(_cfg(ts_col="UPMJ", ts_kind="date"), table, pk=["gldoc"])
    assert v3["effective_upsert_key"] == ["gldoc"]
    assert v3["upsert_key_kind"] == "primary_key"
    assert v3["mode"] == "incremental"


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
    # F0911 carries a reference PK in production, so a date watermark + PK is INCREMENTAL (the chosen
    # poll interval is honoured, NOT clamped to the full-reload floor). Mirror production by setting a
    # PK first (prompt 36: a date marker with NO PK would instead be full-reload → clamped to 12h).
    client.put(
        "/ora2pg/tables/V2_PRO_F0911/primary-key",
        headers=auth_headers,
        json={"pk_columns": ["glkco", "gldoc"]},
    )
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
    assert body["poll_interval_sec"] == 120  # incremental (date + PK) → not clamped
    assert body["mode"] == "incremental"
    assert body["effective_upsert_key"] == ["glkco", "gldoc"]


def test_put_config_date_no_pk_clamps_to_full_reload_floor(client: TestClient, auth_headers: dict[str, str]) -> None:
    # Prompt 36: a date watermark with NO PK can't dedup → full-reload → poll clamped to the 12h floor.
    r = client.put(
        "/streaming/config/V2_PRO_F0911",
        headers=auth_headers,
        json={"enabled": True, "ts_col": "GLUPMJ", "ts_kind": "date", "poll_interval_sec": 120},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["mode"] == "full"
    assert body["effective_upsert_key"] is None
    assert body["poll_interval_sec"] == 43200  # clamped to FULL_RELOAD_MIN_INTERVAL


def test_put_config_sequence_marker_no_pk_is_incremental(client: TestClient, auth_headers: dict[str, str]) -> None:
    # Prompt 36: a sequence/id marker is its own upsert key → incremental even with no PK (poll
    # honoured). Uses GLUPMJ (a real F0911 column) so the ts_col-exists check passes on an
    # Oracle-reachable host; kind=sequence is what exercises the marker-as-key routing here.
    r = client.put(
        "/streaming/config/V2_PRO_F0911",
        headers=auth_headers,
        json={"enabled": True, "ts_col": "GLUPMJ", "ts_kind": "sequence", "poll_interval_sec": 30},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["mode"] == "incremental"
    assert body["effective_upsert_key"] == ["GLUPMJ"]
    assert body["upsert_key_kind"] == "marker"
    assert body["poll_interval_sec"] == 30  # incremental → not clamped


def test_put_config_ignores_primary_key_columns(client: TestClient, auth_headers: dict[str, str]) -> None:
    # Prompt 36 review fix: the PK/upsert key is pk.edit-gated — streaming.configure must NOT be able
    # to set it through the streaming PUT back door. The field is stripped before persist.
    r = client.put(
        "/streaming/config/V2_PRO_F0911",
        headers=auth_headers,
        json={"enabled": True, "primary_key_columns": ["sneaky_col"]},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["primary_key_columns"] != ["sneaky_col"]  # back-door value never persisted


def test_put_config_rejects_bad_ts_time_col(client: TestClient, auth_headers: dict[str, str]) -> None:
    # Prompt 36 review fix: ts_time_col is interpolated into the WHERE predicate → identifier-gated.
    r = client.put(
        "/streaming/config/V2_PRO_F0911",
        headers=auth_headers,
        json={"ts_time_col": "glupmt; drop table x"},
    )
    assert r.status_code == 400


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

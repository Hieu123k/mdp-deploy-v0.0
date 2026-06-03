"""Migration Dashboard v0.0 — additive endpoint tests (no docker / no Oracle needed)."""


def test_dashboard_info(client, auth_headers):
    res = client.get("/ora2pg/info", headers=auth_headers)
    assert res.status_code == 200
    body = res.json()
    assert body["version"] == "v0.0"
    assert body["target_schema"] == "mdp_staging"
    assert body["table_count"] == 3


def test_list_tables(client, auth_headers):
    res = client.get("/ora2pg/tables", headers=auth_headers)
    assert res.status_code == 200
    body = res.json()
    names = {t["table"] for t in body["tables"]}
    assert {"V2_PRO_F0911", "V2_PRO_F0411", "V2_PRO_F4311"} <= names
    for t in body["tables"]:
        assert t["target_table"] == t["table"].lower()
        assert t["target_schema"] == "mdp_staging"


def test_config_preview_is_env_driven_and_redacted(client, auth_headers):
    res = client.get("/ora2pg/tables/V2_PRO_F0911/config-preview", headers=auth_headers)
    assert res.status_code == 200
    conf = res.json()["conf_redacted"]
    # ora2pg.conf shape (mirrors migrate.sh): table + target schema present
    assert "ALLOW            V2_PRO_F0911" in conf
    assert "PG_SCHEMA        mdp_staging" in conf
    assert "VIEW_AS_TABLE    V2_PRO_F0911" in conf
    # secrets must be masked
    assert "ORACLE_PWD       ***" in conf
    assert "PG_PWD       ***" in conf


def test_config_preview_unknown_table_404(client, auth_headers):
    res = client.get("/ora2pg/tables/NOPE/config-preview", headers=auth_headers)
    assert res.status_code == 404


def test_status_endpoint(client, auth_headers):
    res = client.get("/ora2pg/status", headers=auth_headers)
    assert res.status_code == 200
    body = res.json()
    assert body["schema"] == "mdp_staging"
    assert len(body["tables"]) == 3


def test_start_unknown_table_404(client, auth_headers):
    res = client.post("/ora2pg/tables/UNKNOWN/start", headers=auth_headers)
    assert res.status_code == 404


def test_dashboard_requires_auth(client):
    assert client.get("/ora2pg/tables").status_code == 401


def test_runner_start_run_sets_pending_progress(monkeypatch):
    """start_run must register progress without the worker thread (no docker needed)."""
    from app.services import ora2pg_runner
    from app.core.ora2pg_catalog import MIGRATABLE_TABLES

    class _NoThread:
        def __init__(self, *a, **k):
            pass

        def start(self):
            pass

    monkeypatch.setattr(ora2pg_runner.threading, "Thread", _NoThread)
    ora2pg_runner.start_run("run-test-123", MIGRATABLE_TABLES[0])
    snap = ora2pg_runner.get_progress("run-test-123")
    assert snap is not None
    assert snap["run_id"] == "run-test-123"
    assert snap["status"] == "pending"


def test_start_known_table_returns_202(client, auth_headers, monkeypatch):
    """The trigger endpoint creates a run and returns 202 (worker stubbed out)."""
    import app.api.ora2pg_dashboard as mod

    calls = {}
    monkeypatch.setattr(mod, "start_run", lambda run_id, table, **kw: calls.update(run_id=run_id))
    res = client.post("/ora2pg/tables/V2_PRO_F0911/start", headers=auth_headers)
    assert res.status_code == 202
    body = res.json()
    assert body["table"] == "V2_PRO_F0911"
    assert body["run_id"]
    assert calls.get("run_id") == body["run_id"]

"""Reconciliation + audit-columns + repair endpoints (prompt 18). No docker / no Oracle.

The MATCH/MISMATCH *logic* runs on sqlite via reconcile_ora2pg_run(); the per-row audit
columns are proven against real postgres (gated, like test_ora2pg_ddl_commit)."""
import uuid

import pytest
from sqlalchemy import text

from app.core.ora2pg_catalog import MIGRATABLE_TABLES, build_ora2pg_conf
from app.models.migration import MigrationJob, MigrationRun, MigrationValidation


# ---------------------------------------------------------------- conf (repair mode)
def test_build_conf_repair_mode_is_additive():
    t = MIGRATABLE_TABLES[0]
    full = build_ora2pg_conf(t)
    assert "TRUNCATE_TABLE   1" in full  # default unchanged (full reload)

    repair = build_ora2pg_conf(t, truncate=False, where_clause=f"{t.table}[UPMJ >= 124001]")
    assert "TRUNCATE_TABLE   0" in repair  # append
    assert f"WHERE            {t.table}[UPMJ >= 124001]" in repair


# ---------------------------------------------------------------- reconcile (sqlite)
def _seed_job_run(db, target_table: str, *, target_rows: int, source_rows: int) -> MigrationRun:
    db.execute(text(f'DROP TABLE IF EXISTS "{target_table}"'))
    db.execute(text(f'CREATE TABLE "{target_table}" (id integer)'))
    for i in range(target_rows):
        db.execute(text(f'INSERT INTO "{target_table}" (id) VALUES (:i)'), {"i": i})
    job = MigrationJob(
        name=f"ora2pg_{target_table}",
        source_type="oracle",
        migration_tool="ora2pg",
        source_table=target_table.upper(),
        target_schema="mdp_staging",
        target_table=target_table,
        load_mode="full_load",
    )
    db.add(job)
    db.flush()
    run = MigrationRun(
        migration_job_id=job.id,
        run_type="ora2pg_copy",
        trigger_type="dashboard",
        status="success",
        source_row_count=source_rows,
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def test_reconcile_match_sets_validation_status(db_session):
    from app.services.migration_service import reconcile_ora2pg_run

    run = _seed_job_run(db_session, "recon_match_tbl", target_rows=3, source_rows=3)
    result = reconcile_ora2pg_run(db_session, run)

    assert result["validation_status"] == "MATCH"
    assert result["target_row_count"] == 3
    assert result["missed"] == 0
    assert run.validation_status == "MATCH"
    checks = {v.check_name for v in db_session.query(MigrationValidation).filter_by(migration_run_id=run.id)}
    assert "source_target_row_count" in checks


def test_reconcile_mismatch_reports_missed(db_session):
    from app.services.migration_service import reconcile_ora2pg_run

    run = _seed_job_run(db_session, "recon_mismatch_tbl", target_rows=3, source_rows=5)
    result = reconcile_ora2pg_run(db_session, run)

    assert result["validation_status"] == "MISMATCH"
    assert result["missed"] == 2  # 5 source - 3 target
    assert run.validation_status == "MISMATCH"


# ---------------------------------------------------------------- audit columns (postgres)
def _require_pg():
    from app.db.session import engine

    if engine.dialect.name != "postgresql":
        pytest.skip("audit-column test requires postgresql")
    try:
        with engine.connect() as c:
            c.execute(text("SELECT 1"))
    except Exception:
        pytest.skip("postgres not reachable")
    return engine


def test_ensure_audit_cols_default_fill_per_row():
    """_ensure_audit_cols + an ora2pg-style insert (source columns only) → _migrated_at is
    per-row (clock_timestamp) and _migrate_run_id is filled, without changing the row count."""
    engine = _require_pg()
    from app.services.ora2pg_runner import _ensure_audit_cols

    schema, tbl = "mdp_staging", "t_audit_runner_test"
    rid = str(uuid.uuid4())
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as c:
        c.exec_driver_sql(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')
        c.exec_driver_sql(f'DROP TABLE IF EXISTS "{schema}"."{tbl}"')
        c.exec_driver_sql(f'CREATE TABLE "{schema}"."{tbl}" (id int, payload text)')
    try:
        _ensure_audit_cols(schema, tbl, rid)
        with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as c:
            for i in range(3):
                c.exec_driver_sql(f"INSERT INTO \"{schema}\".\"{tbl}\" (id, payload) VALUES ({i}, 'x')")
            row = c.exec_driver_sql(
                f'SELECT count(*), count(DISTINCT _migrated_at), '
                f"count(*) FILTER (WHERE _migrate_run_id = '{rid}'::uuid) "
                f'FROM "{schema}"."{tbl}"'
            ).fetchone()
        assert row[0] == 3  # 1:1 row count preserved
        assert row[1] == 3  # clock_timestamp() per row
        assert row[2] == 3  # _migrate_run_id default applied
    finally:
        with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as c:
            c.exec_driver_sql(f'DROP TABLE IF EXISTS "{schema}"."{tbl}"')


# ---------------------------------------------------------------- endpoints (contract)
def test_verify_endpoint_contract(client, auth_headers):
    res = client.post("/ora2pg/tables/V2_PRO_F0911/verify", headers=auth_headers)
    assert res.status_code == 200
    body = res.json()
    assert body["table"] == "V2_PRO_F0911"
    # verdict field renamed to source_verdict (exact-vs-estimate aware) in the source-count work
    assert "source_verdict" in body and "missed" in body and "source_available" in body


def test_verify_unknown_table_404(client, auth_headers):
    assert client.post("/ora2pg/tables/NOPE/verify", headers=auth_headers).status_code == 404


def test_repair_endpoint_modes(client, auth_headers, monkeypatch):
    import app.api.ora2pg_dashboard as mod

    calls = {}
    monkeypatch.setattr(mod, "start_repair", lambda run_id, table, **kw: calls.setdefault("repair", kw))
    monkeypatch.setattr(mod, "start_run", lambda run_id, table, **kw: calls.setdefault("full", True))

    # watermark mode (F0911 has ts_col + integer cutoff)
    res = client.post("/ora2pg/tables/V2_PRO_F0911/repair?cutoff=124001", headers=auth_headers)
    assert res.status_code == 202
    assert res.json()["mode"] == "watermark"
    assert calls["repair"]["cutoff"] == "124001"

    # fallback full reload (no cutoff, no pk) → mode "full"
    res2 = client.post("/ora2pg/tables/V2_PRO_F0911/repair", headers=auth_headers)
    assert res2.status_code == 202
    assert res2.json()["mode"] == "full"
    assert calls.get("full") is True

    # bad cutoff → 400
    assert client.post("/ora2pg/tables/V2_PRO_F0911/repair?cutoff=abc", headers=auth_headers).status_code == 400


def test_run_report_and_reconciliation_export(client, auth_headers, monkeypatch, db_session):
    import app.api.ora2pg_dashboard as mod

    monkeypatch.setattr(mod, "start_run", lambda run_id, table, **kw: None)
    started = client.post("/ora2pg/tables/V2_PRO_F0411/start", headers=auth_headers)
    run_id = started.json()["run_id"]

    # per-run report (json + csv)
    rj = client.get(f"/ora2pg/runs/{run_id}/report?format=json", headers=auth_headers)
    assert rj.status_code == 200
    assert rj.json()["run_id"] == run_id and "missed" in rj.json()
    rc = client.get(f"/ora2pg/runs/{run_id}/report?format=csv", headers=auth_headers)
    assert rc.status_code == 200
    assert rc.headers["content-type"].startswith("text/csv")
    assert "run_id" in rc.text

    # reconciliation export across all 40 tables (json + csv)
    ej = client.get("/ora2pg/reconciliation?format=json", headers=auth_headers)
    assert ej.status_code == 200
    assert len(ej.json()["tables"]) == 40
    ec = client.get("/ora2pg/reconciliation?format=csv", headers=auth_headers)
    assert ec.status_code == 200 and ec.headers["content-type"].startswith("text/csv")


# ============================================================ Phase 2: PK repair
def test_build_conf_insert_on_conflict_is_additive():
    t = MIGRATABLE_TABLES[0]
    assert "INSERT_ON_CONFLICT" not in build_ora2pg_conf(t)  # default unchanged
    pk = build_ora2pg_conf(t, truncate=False, insert_on_conflict=True)
    assert "INSERT_ON_CONFLICT 1" in pk
    assert "TRUNCATE_TABLE   0" in pk


def test_map_pk_to_view_exact_prefix_and_unmapped():
    from app.services.ora2pg_runner import _map_pk_to_view

    pk, un = _map_pk_to_view({"PK1": [(1, "DOC"), (2, "DCT")]}, {"DOC", "DCT", "KCO"})
    assert pk == ["doc", "dct"] and un == []

    pk2, _ = _map_pk_to_view({"PK1": [(1, "GLDOC"), (2, "GLDCT")]}, {"DOC", "DCT"})  # strip 2-char prefix
    assert pk2 == ["doc", "dct"]

    pk3, un3 = _map_pk_to_view({"PK1": [(1, "ZZZNOPE")]}, {"DOC"})
    assert pk3 is None and "ZZZNOPE" in un3


def test_ensure_unique_index_enables_on_conflict_skip():
    """The crux of PK repair: a UNIQUE index + INSERT … ON CONFLICT DO NOTHING inserts only
    the missing row and silently skips the duplicate (no error, no double)."""
    engine = _require_pg()
    from app.services.ora2pg_runner import _ensure_unique_index

    schema, tbl = "mdp_staging", "t_uix_test"
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as c:
        c.exec_driver_sql(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')
        c.exec_driver_sql(f'DROP TABLE IF EXISTS "{schema}"."{tbl}"')
        c.exec_driver_sql(f'CREATE TABLE "{schema}"."{tbl}" (doc int, dct text, descr text)')
    try:
        _ensure_unique_index(schema, tbl, ["doc", "dct"])
        with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as c:
            c.exec_driver_sql(f"INSERT INTO \"{schema}\".\"{tbl}\" (doc, dct, descr) VALUES (1, 'a', 'orig')")
            c.exec_driver_sql(
                f"INSERT INTO \"{schema}\".\"{tbl}\" (doc, dct, descr) VALUES (1, 'a', 'dup') ON CONFLICT DO NOTHING"
            )
            c.exec_driver_sql(
                f"INSERT INTO \"{schema}\".\"{tbl}\" (doc, dct, descr) VALUES (2, 'b', 'new') ON CONFLICT DO NOTHING"
            )
            rows = c.exec_driver_sql(f'SELECT count(*) FROM "{schema}"."{tbl}"').fetchone()[0]
            kept = c.exec_driver_sql(
                f"SELECT descr FROM \"{schema}\".\"{tbl}\" WHERE doc=1 AND dct='a'"
            ).fetchone()[0]
        assert rows == 2  # dup skipped, new inserted
        assert kept == "orig"  # existing row untouched
    finally:
        with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as c:
            c.exec_driver_sql(f'DROP TABLE IF EXISTS "{schema}"."{tbl}"')


def test_repair_mode_pk(client, auth_headers, monkeypatch, db_session):
    import app.api.ora2pg_dashboard as mod

    job = MigrationJob(
        name="ora2pg_v2_pro_f4101", source_type="oracle", migration_tool="ora2pg",
        target_schema="mdp_staging", target_table="v2_pro_f4101", load_mode="full_load",
        primary_key_columns=["doc", "dct", "kco"],
    )
    db_session.add(job)
    db_session.commit()

    calls = {}
    monkeypatch.setattr(mod, "start_repair", lambda run_id, table, **kw: calls.update(kw))
    res = client.post("/ora2pg/tables/V2_PRO_F4101/repair?mode=pk", headers=auth_headers)
    assert res.status_code == 202
    assert res.json()["mode"] == "pk"
    assert calls.get("mode") == "pk"
    assert calls.get("pk_columns") == ["doc", "dct", "kco"]


def test_repair_mode_pk_without_pk_is_400(client, auth_headers, monkeypatch):
    import app.api.ora2pg_dashboard as mod

    monkeypatch.setattr(mod, "start_repair", lambda *a, **k: None)
    monkeypatch.setattr(mod, "start_run", lambda *a, **k: None)
    res = client.post("/ora2pg/tables/V2_PRO_F4801/repair?mode=pk", headers=auth_headers)
    assert res.status_code == 400


def test_keys_endpoint_lists_40(client, auth_headers):
    res = client.get("/ora2pg/keys", headers=auth_headers)
    assert res.status_code == 200
    body = res.json()
    assert body["total"] == 40 and len(body["tables"]) == 40
    assert all("repair_mode" in t for t in body["tables"])


def test_discover_keys_graceful_without_oracle(client, auth_headers):
    """No docker/Oracle in the test env → discovery returns available=False with all 40 tables
    (pk null), never an error — the contract still holds for `.63`.

    Env-sensitive: this asserts the *no-Oracle* degradation path, so it only applies when Oracle
    is unreachable (e.g. `.63` / CI). On an Oracle-capable host (e.g. `mdp2`, or tipa-mdp running
    pytest during a prod deploy) discovery legitimately returns available=True, which is correct
    behaviour rather than a failure — so we SKIP there to keep the suite green in every environment.
    """
    res = client.post("/ora2pg/discover-keys", headers=auth_headers)
    assert res.status_code == 200  # must never 5xx, Oracle present or not
    body = res.json()
    if body["available"]:
        pytest.skip("Oracle reachable in this environment — the no-Oracle contract does not apply")
    assert body["available"] is False
    assert len(body["results"]) == 40
    assert all(r["pk_columns"] is None for r in body["results"])

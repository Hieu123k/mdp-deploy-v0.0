"""Source-count cache: estimate refresh, exact-on-verify, verdict semantics (estimate is NOT a
MISMATCH), fail-graceful (keep old + stale), and /ora2pg/tables reading cache without Oracle.
All Oracle access is mocked — the real counts run on .63."""
from app.core.ora2pg_catalog import MIGRATABLE_TABLES
from app.services import source_count_service as svc

V0 = MIGRATABLE_TABLES[0].table  # e.g. V2_PRO_F4101


def test_source_verdict_semantics(db_session):
    est = svc.upsert_source_count(
        db_session, source_view="V_EST", target_table="v_est", count=100,
        mode="estimate", approximate=True, status="ok",
    )
    # estimate never yields MATCH/MISMATCH — only ESTIMATE
    assert svc.source_verdict(est, 100) == "ESTIMATE"
    assert svc.source_verdict(est, 50) == "ESTIMATE"

    ex = svc.upsert_source_count(
        db_session, source_view="V_EX", target_table="v_ex", count=100,
        mode="exact", approximate=False, status="ok",
    )
    assert svc.source_verdict(ex, 100) == "MATCH"
    assert svc.source_verdict(ex, 99) == "MISMATCH"
    assert svc.source_verdict(ex, None) == "PENDING"
    assert svc.source_verdict(None, 100) == "PENDING"


def test_refresh_estimates_fills_cache(db_session, monkeypatch):
    fake = {t.table.upper(): {"count": (i + 1) * 1000, "error": None} for i, t in enumerate(MIGRATABLE_TABLES)}
    monkeypatch.setattr(svc, "estimate_oracle_counts", lambda tables: fake)
    res = svc.refresh_estimates(db_session, MIGRATABLE_TABLES)
    assert res["ok"] == len(MIGRATABLE_TABLES) and res["stale"] == 0
    row = svc.get_all_source_counts(db_session)[V0]
    assert row.source_row_count == 1000 and row.count_mode == "estimate" and row.approximate is True and row.status == "ok"


def test_estimate_failure_keeps_old_and_marks_stale(db_session, monkeypatch):
    monkeypatch.setattr(svc, "estimate_oracle_counts",
                        lambda tables: {t.table.upper(): {"count": 777, "error": None} for t in MIGRATABLE_TABLES})
    svc.refresh_estimates(db_session, MIGRATABLE_TABLES)
    monkeypatch.setattr(svc, "estimate_oracle_counts",
                        lambda tables: {t.table.upper(): {"count": None, "error": "oracle down"} for t in MIGRATABLE_TABLES})
    svc.refresh_estimates(db_session, MIGRATABLE_TABLES)
    row = svc.get_all_source_counts(db_session)[V0]
    assert row.source_row_count == 777  # previous good count kept
    assert row.status == "stale" and row.last_error == "oracle down"


def test_tables_endpoint_reads_cache_no_oracle(client, auth_headers, db_session):
    svc.upsert_source_count(
        db_session, source_view=V0, target_table=MIGRATABLE_TABLES[0].target_table,
        count=12345, mode="estimate", approximate=True, status="ok",
    )
    body = client.get("/ora2pg/tables", headers=auth_headers).json()
    row = next(t for t in body["tables"] if t["table"] == V0)
    assert row["source_count"] == 12345
    assert row["source_count_mode"] == "estimate"
    assert row["source_verdict"] == "ESTIMATE"  # estimate -> NOT a red MISMATCH


def test_verify_writes_exact_to_cache(client, auth_headers, db_session, monkeypatch):
    monkeypatch.setattr(svc, "exact_oracle_count", lambda table: {"count": 999, "error": None})
    res = client.post(f"/ora2pg/tables/{V0}/verify", headers=auth_headers)
    assert res.status_code == 200
    body = res.json()
    assert body["source_count"] == 999 and body["source_count_mode"] == "exact"
    cached = svc.get_all_source_counts(db_session)[V0]
    assert cached.count_mode == "exact" and cached.source_row_count == 999 and cached.approximate is False


def test_verify_oracle_unreachable_stays_stale(client, auth_headers, db_session, monkeypatch):
    # seed an estimate, then an exact verify that fails -> keep estimate, status stale, verdict not MISMATCH
    svc.upsert_source_count(db_session, source_view=V0, target_table=MIGRATABLE_TABLES[0].target_table,
                            count=500, mode="estimate", approximate=True, status="ok")
    monkeypatch.setattr(svc, "exact_oracle_count", lambda table: {"count": None, "error": "oracle unreachable"})
    body = client.post(f"/ora2pg/tables/{V0}/verify", headers=auth_headers).json()
    assert body["source_stale"] is True
    cached = svc.get_all_source_counts(db_session)[V0]
    assert cached.source_row_count == 500 and cached.status == "stale"  # old estimate kept


def test_refresher_off_by_default():
    from app.services.source_count_refresher import SourceCountRefresher
    assert SourceCountRefresher().start() is False  # ORA2PG_SOURCE_COUNT_ENABLED default false

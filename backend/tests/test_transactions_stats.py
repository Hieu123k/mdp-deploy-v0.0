"""Prompt 51 - GET /transactions/stats (all-time status counts, no 500 cap) + the failed filter."""
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.services.transaction_logger import log_transaction


def _seed(db: Session, statuses: list[str]) -> None:
    for status in statuses:
        log_transaction(db, direction="inbound", protocol="rest", status=status, endpoint="/x")
    db.commit()


def test_t1_stats_counts_group_by_status(
    client: TestClient, auth_headers: dict[str, str], db_session: Session
) -> None:
    _seed(db_session, ["success"] * 3 + ["failed"] * 2)
    r = client.get("/transactions/stats", headers=auth_headers)
    assert r.status_code == 200, r.json()
    body = r.json()
    assert body["total"] == 5
    assert body["by_status"]["success"] == 3
    assert body["by_status"]["failed"] == 2


def test_t1_stats_is_all_time_not_capped_at_500(
    client: TestClient, auth_headers: dict[str, str], db_session: Session
) -> None:
    # More rows than the list route's hard cap (500): stats must count ALL of them, while the list
    # route is still capped - this is exactly the bug the Dashboard had.
    _seed(db_session, ["success"] * 503 + ["failed"] * 4)
    stats = client.get("/transactions/stats", headers=auth_headers).json()
    assert stats["total"] == 507
    assert stats["by_status"]["success"] == 503
    assert stats["by_status"]["failed"] == 4
    listed = client.get("/transactions?limit=500", headers=auth_headers)
    assert len(listed.json()) == 500  # list route capped; stats route is not


def test_t1_stats_requires_auth(client: TestClient, db_session: Session) -> None:
    r = client.get("/transactions/stats")
    assert r.status_code in (401, 403)


def test_v_list_filter_failed_returns_only_failed(
    client: TestClient, auth_headers: dict[str, str], db_session: Session
) -> None:
    # The FE filter sends status=failed (prompt 51 V); confirm the API filters correctly.
    _seed(db_session, ["success", "failed", "failed", "success"])
    rows = client.get("/transactions?status=failed", headers=auth_headers).json()
    assert len(rows) == 2
    assert all(t["status"] == "failed" for t in rows)
    ok = client.get("/transactions?status=success", headers=auth_headers).json()
    assert len(ok) == 2
    assert all(t["status"] == "success" for t in ok)

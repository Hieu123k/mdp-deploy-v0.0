"""Multi-Verify queue: API surface + the single worker runs jobs SEQUENTIALLY and keeps going
past a failing table."""
from __future__ import annotations

import time

from fastapi.testclient import TestClient

from app.services import verify_service


def _wait_finished(get_status, *, tries: int = 200, delay: float = 0.05):
    for _ in range(tries):
        st = get_status()
        if st and st.get("finished"):
            return st
        time.sleep(delay)
    return get_status()


def test_verify_batch_empty_rejected(client: TestClient, auth_headers: dict[str, str]) -> None:
    assert client.post("/ora2pg/verify-batch", headers=auth_headers, json={"tables": []}).status_code == 400


def test_verify_batch_unknown_batch_404(client: TestClient, auth_headers: dict[str, str]) -> None:
    assert client.get("/ora2pg/verify-batch/not-a-batch", headers=auth_headers).status_code == 404


def test_verify_batch_requires_auth(client: TestClient) -> None:
    assert client.post("/ora2pg/verify-batch", json={"tables": ["X"]}).status_code == 401


def test_verify_batch_unknown_table_errors_gracefully(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    # An unknown table never touches the DB/Oracle — the worker records it as error.
    r = client.post("/ora2pg/verify-batch", headers=auth_headers, json={"tables": ["NOPE_TABLE_XYZ"]})
    assert r.status_code == 202
    bid = r.json()["batch_id"]
    st = _wait_finished(
        lambda: client.get(f"/ora2pg/verify-batch/{bid}", headers=auth_headers).json()
    )
    assert st["finished"] is True
    assert st["tables"]["NOPE_TABLE_XYZ"]["status"] == "error"


def test_queue_runs_sequentially_and_skips_failures(monkeypatch) -> None:
    """Worker unit test (no DB/Oracle): jobs run one-at-a-time in order; a bad table errors and
    the queue continues."""
    order: list[str] = []

    class _T:
        def __init__(self, name: str) -> None:
            self.table = name
            self.target_table = name.lower()

    def fake_get_table(name: str):
        return None if name == "BAD" else _T(name)

    def fake_perform(_db, table):
        order.append(table.table)
        time.sleep(0.02)  # make any concurrency visible as interleaving
        return {"source_verdict": "PENDING", "target_rows": None, "source_count": None, "missed": None}

    monkeypatch.setattr(verify_service, "get_table", fake_get_table)
    monkeypatch.setattr(verify_service, "perform_verify", fake_perform)

    bid = verify_service.enqueue_batch(["A", "B", "BAD", "C"])
    st = _wait_finished(lambda: verify_service.get_batch_status(bid))

    assert st["finished"] is True
    assert order == ["A", "B", "C"]  # sequential; BAD skipped (errored, not run)
    assert st["tables"]["A"]["status"] == "done"
    assert st["tables"]["BAD"]["status"] == "error"
    assert st["tables"]["C"]["status"] == "done"

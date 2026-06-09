"""Primary-Key edit endpoint: admin-only (403/200), validation, persistence onto the canonical
migration_jobs.primary_key_columns. (Index rebuild needs a live Postgres target; off-Postgres it
degrades to index_rebuilt=false without error — asserted graceful.)"""
from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.schemas.user import UserCreate
from app.services.user_service import create_user


def _login(client: TestClient, username: str, password: str) -> str:
    r = client.post("/auth/login", json={"username": username, "password": password})
    return r.json()["access_token"]


def test_set_pk_requires_admin(client: TestClient, db_session: Session) -> None:
    create_user(db_session, UserCreate(username="vw", email="vw@mdp.local", password="passw0rd", role="viewer"))
    tok = _login(client, "vw", "passw0rd")
    r = client.put(
        "/ora2pg/tables/V2_PRO_F0911/primary-key",
        headers={"Authorization": f"Bearer {tok}"},
        json={"pk_columns": ["gldoc"]},
    )
    assert r.status_code == 403


def test_set_pk_admin_persists(client: TestClient, auth_headers: dict[str, str]) -> None:
    r = client.put(
        "/ora2pg/tables/V2_PRO_F0911/primary-key",
        headers=auth_headers,
        json={"pk_columns": ["gldoc", "gldct"]},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["pk_columns"] == ["gldoc", "gldct"]  # composite, lower-cased
    assert "index_rebuilt" in body and "index_error" in body
    # reflected in the tables list (canonical store)
    tables = client.get("/ora2pg/tables", headers=auth_headers).json()["tables"]
    f0911 = next(t for t in tables if t["table"] == "V2_PRO_F0911")
    assert f0911["pk_columns"] == ["gldoc", "gldct"]


def test_set_pk_empty_400(client: TestClient, auth_headers: dict[str, str]) -> None:
    r = client.put("/ora2pg/tables/V2_PRO_F0911/primary-key", headers=auth_headers, json={"pk_columns": []})
    assert r.status_code == 400


def test_set_pk_rejects_injection_identifier(client: TestClient, auth_headers: dict[str, str]) -> None:
    # DDL-injection / bad identifier must be rejected up-front (never persisted, never reaches DDL).
    for bad in ['gldoc") ; DROP TABLE x; --', "col with space", "weird-name", "1col", "Col;"]:
        r = client.put(
            "/ora2pg/tables/V2_PRO_F0911/primary-key", headers=auth_headers, json={"pk_columns": [bad]}
        )
        assert r.status_code == 400, f"expected 400 for {bad!r}, got {r.status_code}"


def test_set_pk_unknown_table_404(client: TestClient, auth_headers: dict[str, str]) -> None:
    r = client.put("/ora2pg/tables/NOPE/primary-key", headers=auth_headers, json={"pk_columns": ["x"]})
    assert r.status_code == 404


def test_set_pk_requires_auth(client: TestClient) -> None:
    assert client.put("/ora2pg/tables/V2_PRO_F0911/primary-key", json={"pk_columns": ["x"]}).status_code == 401


def test_discover_keys_per_table_unknown_404(client: TestClient, auth_headers: dict[str, str]) -> None:
    assert client.post("/ora2pg/discover-keys?table=NOPE", headers=auth_headers).status_code == 404

"""RBAC BE-enforce: require_role returns 403 for the wrong role, 200 for the right one."""
from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.schemas.user import UserCreate
from app.services.user_service import create_user


def _login(client: TestClient, username: str, password: str) -> str:
    r = client.post("/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _seed(db: Session, username: str, role: str) -> None:
    create_user(
        db,
        UserCreate(username=username, email=f"{username}@mdp.local", password="passw0rd", role=role),
    )


def test_users_route_blocks_viewer(client: TestClient, db_session: Session) -> None:
    _seed(db_session, "viewer1", "viewer")
    tok = _login(client, "viewer1", "passw0rd")
    r = client.get("/users", headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 403


def test_users_route_allows_admin(client: TestClient, auth_headers: dict[str, str]) -> None:
    assert client.get("/users", headers=auth_headers).status_code == 200


def test_create_user_blocked_for_non_admin(client: TestClient, db_session: Session) -> None:
    _seed(db_session, "de1", "data_engineer")
    tok = _login(client, "de1", "passw0rd")
    r = client.post(
        "/users",
        headers={"Authorization": f"Bearer {tok}"},
        json={"username": "x", "email": "x@mdp.local", "password": "passw0rd", "role": "viewer"},
    )
    assert r.status_code == 403


def test_users_route_requires_auth(client: TestClient) -> None:
    assert client.get("/users").status_code == 401

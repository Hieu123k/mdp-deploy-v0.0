"""User preferences: per-user theme (self) + admin-controlled nav config."""
from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.schemas.user import UserCreate
from app.services.user_service import create_user


def _login(client: TestClient, username: str, password: str) -> str:
    r = client.post("/auth/login", json={"username": username, "password": password})
    return r.json()["access_token"]


def test_default_theme_light(client: TestClient, auth_headers: dict[str, str]) -> None:
    r = client.get("/preferences/me", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["theme"] == "light"


def test_update_and_persist_theme(client: TestClient, auth_headers: dict[str, str]) -> None:
    r = client.put("/preferences/me", headers=auth_headers, json={"theme": "dark"})
    assert r.status_code == 200 and r.json()["theme"] == "dark"
    # persists across requests
    assert client.get("/preferences/me", headers=auth_headers).json()["theme"] == "dark"


def test_invalid_theme_rejected(client: TestClient, auth_headers: dict[str, str]) -> None:
    assert client.put("/preferences/me", headers=auth_headers, json={"theme": "rainbow"}).status_code == 400


def test_admin_sets_user_nav_config(client: TestClient, auth_headers: dict[str, str], db_session: Session) -> None:
    u = create_user(
        db_session,
        UserCreate(username="navuser", email="navuser@mdp.local", password="passw0rd", role="viewer"),
    )
    r = client.put(
        f"/preferences/users/{u.id}",
        headers=auth_headers,
        json={"nav_config": {"/users": {"visible": False, "label": "Accounts", "order": 2}}},
    )
    assert r.status_code == 200
    nav = r.json()["nav_config"]
    assert nav["/users"]["visible"] is False
    assert nav["/users"]["label"] == "Accounts"


def test_admin_prefs_blocked_for_non_admin(client: TestClient, db_session: Session) -> None:
    create_user(
        db_session,
        UserCreate(username="viewer2", email="viewer2@mdp.local", password="passw0rd", role="viewer"),
    )
    tok = _login(client, "viewer2", "passw0rd")
    assert client.get("/preferences/users", headers={"Authorization": f"Bearer {tok}"}).status_code == 403

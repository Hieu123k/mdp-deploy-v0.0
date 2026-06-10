"""RBAC capability layer (prompt 34): seed defaults, require_permission enforce (allow/deny),
role API matrix + anti-escalation. role_permissions table is created by Base.metadata (conftest);
the boot seed does not run under TestClient, so tests seed explicitly."""
from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.schemas.user import UserCreate
from app.services.permission_service import (
    get_permission_matrix,
    role_has_permission,
    seed_role_permissions,
)
from app.services.user_service import create_user


def _login(client: TestClient, username: str, password: str = "passw0rd") -> str:
    return client.post("/auth/login", json={"username": username, "password": password}).json()["access_token"]


def _h(tok: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {tok}"}


def test_seed_defaults_idempotent(db_session: Session) -> None:
    n = seed_role_permissions(db_session)
    assert n > 0
    assert role_has_permission(db_session, "admin", "role.manage")  # admin implicit-full
    assert role_has_permission(db_session, "data_engineer", "migration.run")
    assert role_has_permission(db_session, "api_manager", "api_key.create")
    assert not role_has_permission(db_session, "viewer", "migration.run")  # view-only
    assert not role_has_permission(db_session, "data_engineer", "users.manage")  # admin-only never granted
    assert seed_role_permissions(db_session) == 0  # idempotent


def test_role_api_admin_only(client: TestClient, db_session: Session) -> None:
    create_user(db_session, UserCreate(username="vwr", email="vwr@mdp.local", password="passw0rd", role="viewer"))
    assert client.get("/roles/permissions", headers=_h(_login(client, "vwr"))).status_code == 403


def test_role_api_matrix_and_anti_escalation(client: TestClient, auth_headers: dict[str, str], db_session: Session) -> None:
    seed_role_permissions(db_session)
    m = client.get("/roles/permissions", headers=auth_headers).json()
    assert m["roles"]["admin"]["role.manage"] is True
    assert set(m["admin_only"]) == {"role.manage", "users.manage"}

    # grant a normal permission to viewer → OK
    r = client.put("/roles/permissions", headers=auth_headers, json={"roles": {"viewer": {"migration.run": True}}})
    assert r.status_code == 200
    assert r.json()["roles"]["viewer"]["migration.run"] is True

    # grant an ADMIN-ONLY permission to a non-admin role → 400 (anti-escalation)
    r2 = client.put("/roles/permissions", headers=auth_headers, json={"roles": {"data_engineer": {"users.manage": True}}})
    assert r2.status_code == 400
    assert not role_has_permission(db_session, "data_engineer", "users.manage")

    # admin role is never written (self-lock protection) — payload for admin is ignored, stays full
    client.put("/roles/permissions", headers=auth_headers, json={"roles": {"admin": {"role.manage": False}}})
    assert get_permission_matrix(db_session)["roles"]["admin"]["role.manage"] is True


def test_require_permission_allow_deny(client: TestClient, db_session: Session) -> None:
    seed_role_permissions(db_session)
    create_user(db_session, UserCreate(username="de", email="de@mdp.local", password="passw0rd", role="data_engineer"))
    create_user(db_session, UserCreate(username="vw2", email="vw2@mdp.local", password="passw0rd", role="viewer"))
    body = {"enabled": False, "granularity": "day", "poll_interval_sec": 300, "lookback_days": 1}
    # data_engineer has streaming.configure → 200
    assert client.put("/streaming/config/V2_PRO_F0911", headers=_h(_login(client, "de")), json=body).status_code == 200
    # viewer lacks it → 403 (BE enforce, not just hidden UI)
    assert client.put("/streaming/config/V2_PRO_F0911", headers=_h(_login(client, "vw2")), json=body).status_code == 403

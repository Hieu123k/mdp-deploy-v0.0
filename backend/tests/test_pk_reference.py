"""PK reference seed: public-doc default → canonical, pk_source priority (manual > scanned >
reference), warnings for risky tables. Runs without Oracle (seed needs no DB/target access)."""
from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from sqlalchemy import select

from app.models.migration import MigrationJob
from app.services.user_service import create_user
from app.schemas.user import UserCreate
from app.services.pk_reference_service import REFERENCE, reference_pk, seed_reference_primary_keys


def _f(tables, name):
    return next(t for t in tables if t["table"] == name)


def _job(db: Session, needle: str) -> MigrationJob:
    """Fetch a seeded MigrationJob by a substring of its name (e.g. 'f0911')."""
    return next(j for j in db.scalars(select(MigrationJob)).all() if needle in (j.name or "").lower())


def test_reference_loaded_40() -> None:
    assert len(REFERENCE) == 40
    # physical base columns lower-cased = the target/view 1:1 map
    assert reference_pk("V2_PRO_F0911") == ["gldct", "gldoc", "glkco", "gldgj", "gljeln", "gllt", "glextl"]


def test_seed_sets_reference_default(client: TestClient, auth_headers: dict[str, str], db_session: Session) -> None:
    n = seed_reference_primary_keys(db_session)
    assert n == 40
    tables = client.get("/ora2pg/tables", headers=auth_headers).json()["tables"]
    f0911 = _f(tables, "V2_PRO_F0911")
    assert f0911["pk_source"] == "reference"  # default source, no scan needed
    assert f0911["pk_columns"] == ["gldct", "gldoc", "glkco", "gldgj", "gljeln", "gllt", "glextl"]


def test_manual_overrides_and_reseed_does_not_clobber(client: TestClient, auth_headers: dict[str, str], db_session: Session) -> None:
    seed_reference_primary_keys(db_session)
    r = client.put("/ora2pg/tables/V2_PRO_F0911/primary-key", headers=auth_headers, json={"pk_columns": ["gldoc"]})
    assert r.status_code == 200
    seed_reference_primary_keys(db_session)  # re-seed must NOT override a manual PK
    f0911 = _f(client.get("/ora2pg/tables", headers=auth_headers).json()["tables"], "V2_PRO_F0911")
    assert f0911["pk_source"] == "manual"
    assert f0911["pk_columns"] == ["gldoc"]


def test_reference_warns_surrogate_and_name_mismatch(client: TestClient, auth_headers: dict[str, str], db_session: Session) -> None:
    seed_reference_primary_keys(db_session)
    tables = client.get("/ora2pg/tables", headers=auth_headers).json()["tables"]
    f4111 = _f(tables, "V2_PRO_F4111")  # pk_type=surrogate (UKID)
    assert f4111["pk_warning"] and "surrogate" in f4111["pk_warning"].lower()
    f4140 = _f(tables, "V2_PRO_F4140")  # name_match=N
    assert f4140["pk_warning"] and "name" in f4140["pk_warning"].lower()


def test_reseed_does_not_clobber_scanned(client: TestClient, auth_headers: dict[str, str], db_session: Session) -> None:
    """Review HIGH #1: a discovered (scanned) PK must survive re-seed — priority manual > scanned >
    reference, so a container restart never reverts an empirically-found key to the reference guess."""
    seed_reference_primary_keys(db_session)
    job = _job(db_session, "f0911")
    job.primary_key_columns = ["gldoc", "glkco"]
    job.config = {**(job.config or {}), "pk_source": "scanned"}
    db_session.add(job)
    db_session.commit()
    seed_reference_primary_keys(db_session)  # re-seed must NOT touch a scanned PK
    f0911 = _f(client.get("/ora2pg/tables", headers=auth_headers).json()["tables"], "V2_PRO_F0911")
    assert f0911["pk_source"] == "scanned"
    assert f0911["pk_columns"] == ["gldoc", "glkco"]


def test_discover_keys_requires_admin(client: TestClient, db_session: Session) -> None:
    """Review HIGH #2: discover-keys mutates the canonical + streaming PK, so it must be admin-only
    (403 for a non-admin), matching the manual PK-set endpoint."""
    create_user(db_session, UserCreate(username="v1", email="v1@mdp.local", password="passw0rd", role="viewer"))
    tok = client.post("/auth/login", json={"username": "v1", "password": "passw0rd"}).json()["access_token"]
    r = client.post("/ora2pg/discover-keys", headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 403

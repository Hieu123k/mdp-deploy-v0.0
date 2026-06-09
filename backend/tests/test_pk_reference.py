"""PK reference seed: public-doc default → canonical, pk_source priority (manual > reference),
warnings for risky tables. Runs without Oracle (seed needs no DB/target access)."""
from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.services.pk_reference_service import REFERENCE, reference_pk, seed_reference_primary_keys


def _f(tables, name):
    return next(t for t in tables if t["table"] == name)


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

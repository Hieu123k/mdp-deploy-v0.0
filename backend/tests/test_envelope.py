"""Prompt 41 — integration response envelope {code, message, data}, SCOPED to /inbound + /outbound.

Asserts the envelope contract on the two integration routers, and (EV6) that an internal/FE endpoint
is NOT wrapped, so the frontend's raw shapes are untouched.
"""
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.api.envelope import EnvelopeCode, code_for_status
from tests.test_api_keys import create_external_api_key
from tests.test_inbound import create_invoice_model, create_sqlite_generated_table


def test_code_catalog_is_the_single_source() -> None:
    # The numeric catalog lives in one place and maps the documented statuses.
    assert (EnvelopeCode.SUCCESS, EnvelopeCode.PARTIAL) == (0, 1)
    assert code_for_status(200) == 0
    assert code_for_status(207) == 1
    assert code_for_status(400) == 1001
    assert code_for_status(401) == 1002
    assert code_for_status(403) == 1003
    assert code_for_status(404) == 1004
    assert code_for_status(422) == 1005
    assert code_for_status(429) == 1006
    assert code_for_status(502) == 2001
    assert code_for_status(504) == 2002
    assert code_for_status(500) == 2003
    assert code_for_status(409) == 1001  # not in catalog → generic 4xx fallback


def test_ev1_inbound_success_envelope(client: TestClient, auth_headers: dict[str, str], db_session: Session) -> None:
    create_invoice_model(client, auth_headers)
    create_sqlite_generated_table(db_session)
    r = client.post("/inbound/invoice", headers=auth_headers, json={"invoice_no": "INV-001", "amount": 9.5})
    assert r.status_code == 200
    body = r.json()
    assert body["code"] == 0
    assert set(body) == {"code", "message", "data"}
    assert body["data"]["status"] == "success"
    assert body["data"]["model"] == "invoice"
    assert "record_id" in body["data"]


def test_ev2_inbound_missing_field_422_envelope(client: TestClient, auth_headers: dict[str, str], db_session: Session) -> None:
    create_invoice_model(client, auth_headers)
    create_sqlite_generated_table(db_session)
    r = client.post("/inbound/invoice", headers=auth_headers, json={"amount": 9.5})
    assert r.status_code == 422
    body = r.json()
    assert body["code"] == 1005
    assert body["data"]["errors"][0]["field"] == "invoice_no"
    assert "msg" in body["data"]["errors"][0]


def test_ev3_inbound_403_and_404_envelope(client: TestClient, auth_headers: dict[str, str], db_session: Session) -> None:
    create_invoice_model(client, auth_headers)
    create_sqlite_generated_table(db_session)
    # 403: a key scoped to another model
    key = create_external_api_key(client, auth_headers, directions=["inbound"], models=["other"])["api_key"]
    forbidden = client.post("/inbound/invoice", headers={"X-API-Key": key}, json={"invoice_no": "X", "amount": 1})
    assert forbidden.status_code == 403
    assert forbidden.json()["code"] == 1003
    assert forbidden.json()["data"] is None
    # 404: unknown model
    missing = client.post("/inbound/missing_model", headers=auth_headers, json={"id": "1"})
    assert missing.status_code == 404
    assert missing.json()["code"] == 1004
    assert missing.json()["data"] is None


def test_ev4_outbound_success_envelope(client: TestClient, auth_headers: dict[str, str], db_session: Session) -> None:
    create_invoice_model(client, auth_headers)
    create_sqlite_generated_table(db_session)
    client.post("/inbound/invoice", headers=auth_headers, json={"invoice_no": "INV-001", "amount": 9.5})
    r = client.get("/outbound/invoice", headers=auth_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["code"] == 0
    assert body["data"]["count"] == 1
    assert body["data"]["data"][0]["invoice_no"] == "INV-001"


def test_ev5_outbound_error_envelope(client: TestClient, auth_headers: dict[str, str], db_session: Session) -> None:
    create_invoice_model(client, auth_headers)
    create_sqlite_generated_table(db_session)
    # invalid filter → 422 with errors[]
    r = client.get("/outbound/invoice?raw_payload=x", headers=auth_headers)
    assert r.status_code == 422
    assert r.json()["code"] == 1005
    assert r.json()["data"]["errors"]
    # unknown model → 404, data null
    missing = client.get("/outbound/missing_model", headers=auth_headers)
    assert missing.status_code == 404
    assert missing.json()["code"] == 1004
    assert missing.json()["data"] is None


def test_ev7_router_level_errors_on_integration_paths_are_enveloped(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    # 405 / unrouted-404 are raised by Starlette BEFORE the route handler, so they bypass
    # EnvelopeRoute. The app-level backstop re-wraps them for the integration surface.
    # Wrong method on /inbound (only POST defined) → 405 enveloped (405 → 4xx fallback 1001).
    wrong_method_in = client.get("/inbound/invoice", headers=auth_headers)
    assert wrong_method_in.status_code == 405
    body = wrong_method_in.json()
    assert set(body) == {"code", "message", "data"}
    assert body["code"] == 1001
    assert body["data"] is None
    # Wrong method on /outbound (only GET defined) → 405 enveloped.
    wrong_method_out = client.post("/outbound/invoice", headers=auth_headers, json={})
    assert wrong_method_out.status_code == 405
    assert wrong_method_out.json()["code"] == 1001
    assert wrong_method_out.json()["data"] is None
    # Unrouted path under the integration prefix → 404 enveloped.
    unrouted = client.get("/inbound", headers=auth_headers)
    assert unrouted.status_code == 404
    assert unrouted.json()["code"] == 1004
    assert unrouted.json()["data"] is None


def test_ev7b_router_level_errors_on_internal_paths_stay_raw(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    # Non-regression: the same backstop must NOT touch internal/FE routes — a 405 there keeps
    # FastAPI's raw {detail} shape (no envelope), so the frontend is unaffected.
    wrong_method = client.post("/health")
    assert wrong_method.status_code == 405
    assert "code" not in wrong_method.json()
    assert wrong_method.json()["detail"] == "Method Not Allowed"


def test_ev6_internal_endpoints_are_not_enveloped(client: TestClient, auth_headers: dict[str, str]) -> None:
    # EV6 / FE non-regression: internal/FE routes keep their RAW shape (no {code,message,data}).
    models = client.get("/data-models", headers=auth_headers)
    assert models.status_code == 200
    assert isinstance(models.json(), list)  # raw list, NOT an envelope object

    keys = client.get("/api-keys", headers=auth_headers)
    assert keys.status_code == 200
    assert isinstance(keys.json(), list)

    streaming = client.get("/streaming/status", headers=auth_headers)
    assert streaming.status_code == 200
    assert "code" not in streaming.json() or "loop" in streaming.json()  # raw streaming status shape

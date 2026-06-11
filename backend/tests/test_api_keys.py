from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from tests.test_data_models import type_a_payload
from tests.test_inbound import create_sqlite_generated_table


def create_external_api_key(
    client: TestClient,
    auth_headers: dict[str, str],
    *,
    directions: list[str] | None = None,
    models: list[str] | None = None,
    source_system: str = "ERP",
    expires_at: str | None = None,
) -> dict:
    payload = {
        "name": "ERP integration",
        "description": "Integration key",
        "source_system": source_system,
        "allowed_directions": directions or ["inbound", "outbound"],
        "allowed_models": models,
        "expires_at": expires_at,
    }
    response = client.post("/api-keys", headers=auth_headers, json=payload)
    assert response.status_code == 201
    return response.json()


def create_invoice_model_and_table(
    client: TestClient,
    auth_headers: dict[str, str],
    db_session: Session,
) -> None:
    response = client.post("/data-models", headers=auth_headers, json=type_a_payload())
    assert response.status_code == 201
    create_sqlite_generated_table(db_session)


def test_create_api_key_returns_plain_key_once(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    created = create_external_api_key(client, auth_headers)

    assert created["api_key"].startswith("mdp_live_")
    assert created["key_prefix"] == created["api_key"][:16]
    assert "hashed_key" not in created


def test_list_api_keys_does_not_return_plain_key(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    create_external_api_key(client, auth_headers)

    response = client.get("/api-keys", headers=auth_headers)

    assert response.status_code == 200
    assert "api_key" not in response.json()[0]
    assert "hashed_key" not in response.json()[0]


def test_valid_api_key_can_call_inbound(
    client: TestClient,
    auth_headers: dict[str, str],
    db_session: Session,
) -> None:
    create_invoice_model_and_table(client, auth_headers, db_session)
    # Prompt 40: allowed_models is an explicit allow-list — scope the key to the model it uses.
    api_key = create_external_api_key(client, auth_headers, models=["invoice"])["api_key"]

    response = client.post(
        "/inbound/invoice",
        headers={"X-API-Key": api_key},
        json={"invoice_no": "INV-001", "amount": 98.5},
    )

    assert response.status_code == 200


def test_valid_api_key_can_call_outbound(
    client: TestClient,
    auth_headers: dict[str, str],
    db_session: Session,
) -> None:
    create_invoice_model_and_table(client, auth_headers, db_session)
    client.post(
        "/inbound/invoice",
        headers=auth_headers,
        json={"invoice_no": "INV-001", "amount": 98.5},
    )
    api_key = create_external_api_key(client, auth_headers, models=["invoice"])["api_key"]

    response = client.get("/outbound/invoice", headers={"X-API-Key": api_key})

    assert response.status_code == 200
    assert response.json()["code"] == 0  # envelope (prompt 41)
    assert response.json()["data"]["count"] == 1


def test_inbound_only_key_cannot_call_outbound(
    client: TestClient,
    auth_headers: dict[str, str],
    db_session: Session,
) -> None:
    create_invoice_model_and_table(client, auth_headers, db_session)
    api_key = create_external_api_key(client, auth_headers, directions=["inbound"])["api_key"]

    response = client.get("/outbound/invoice", headers={"X-API-Key": api_key})

    assert response.status_code == 403


def test_outbound_only_key_cannot_call_inbound(
    client: TestClient,
    auth_headers: dict[str, str],
    db_session: Session,
) -> None:
    create_invoice_model_and_table(client, auth_headers, db_session)
    api_key = create_external_api_key(client, auth_headers, directions=["outbound"])["api_key"]

    response = client.post(
        "/inbound/invoice",
        headers={"X-API-Key": api_key},
        json={"invoice_no": "INV-001", "amount": 98.5},
    )

    assert response.status_code == 403


def test_model_restricted_key_cannot_access_invoice(
    client: TestClient,
    auth_headers: dict[str, str],
    db_session: Session,
) -> None:
    create_invoice_model_and_table(client, auth_headers, db_session)
    api_key = create_external_api_key(client, auth_headers, models=["quality_result"])["api_key"]

    response = client.get("/outbound/invoice", headers={"X-API-Key": api_key})

    assert response.status_code == 403


def test_inactive_api_key_fails(
    client: TestClient,
    auth_headers: dict[str, str],
    db_session: Session,
) -> None:
    create_invoice_model_and_table(client, auth_headers, db_session)
    created = create_external_api_key(client, auth_headers)
    client.delete(f"/api-keys/{created['id']}", headers=auth_headers)

    response = client.get("/outbound/invoice", headers={"X-API-Key": created["api_key"]})

    assert response.status_code == 401


def test_delete_api_key_removes_it_and_keeps_transaction_log(
    client: TestClient,
    auth_headers: dict[str, str],
    db_session: Session,
) -> None:
    # Prompt 37 fix: DELETE is a real (hard) delete — the key disappears from the list — and it
    # de-references any child transactions instead of hitting the FK RESTRICT, so the audit log stays.
    import uuid as _uuid

    from app.models.transaction import Transaction

    created = create_external_api_key(client, auth_headers)
    txn = Transaction(
        direction="outbound", protocol="rest", status="success",
        auth_type="api_key", api_key_id=_uuid.UUID(created["id"]),
    )
    db_session.add(txn)
    db_session.commit()
    txn_id = txn.id

    resp = client.delete(f"/api-keys/{created['id']}", headers=auth_headers)
    assert resp.status_code == 204

    listed = client.get("/api-keys", headers=auth_headers).json()
    assert all(k["id"] != created["id"] for k in listed)  # truly gone, not just disabled

    db_session.expire_all()
    kept = db_session.get(Transaction, txn_id)
    assert kept is not None and kept.api_key_id is None  # log preserved, de-referenced


def test_expired_api_key_fails(
    client: TestClient,
    auth_headers: dict[str, str],
    db_session: Session,
) -> None:
    create_invoice_model_and_table(client, auth_headers, db_session)
    expires_at = (datetime.now(UTC) - timedelta(days=1)).isoformat()
    api_key = create_external_api_key(client, auth_headers, expires_at=expires_at)["api_key"]

    response = client.get("/outbound/invoice", headers={"X-API-Key": api_key})

    assert response.status_code == 401


def test_invalid_api_key_fails(client: TestClient) -> None:
    response = client.get("/outbound/invoice", headers={"X-API-Key": "mdp_live_bad"})

    assert response.status_code == 401


def test_jwt_still_works_for_inbound_and_outbound(
    client: TestClient,
    auth_headers: dict[str, str],
    db_session: Session,
) -> None:
    create_invoice_model_and_table(client, auth_headers, db_session)

    inbound = client.post(
        "/inbound/invoice",
        headers=auth_headers,
        json={"invoice_no": "INV-001", "amount": 98.5},
    )
    outbound = client.get("/outbound/invoice", headers=auth_headers)

    assert inbound.status_code == 200
    assert outbound.status_code == 200


def test_transaction_log_records_auth_type_and_source_system(
    client: TestClient,
    auth_headers: dict[str, str],
    db_session: Session,
) -> None:
    create_invoice_model_and_table(client, auth_headers, db_session)
    created = create_external_api_key(
        client,
        auth_headers,
        models=["invoice"],  # prompt 40: explicit allow-list
        source_system="QMS",
    )

    client.post(
        "/inbound/invoice",
        headers={"X-API-Key": created["api_key"]},
        json={"invoice_no": "INV-001", "amount": 98.5},
    )
    response = client.get(
        "/transactions?direction=inbound&status=success",
        headers=auth_headers,
    )
    transaction = response.json()[0]

    assert transaction["auth_type"] == "api_key"
    assert transaction["api_key_id"] == created["id"]
    assert transaction["source_system"] == "QMS"


def test_ak1_empty_allowed_models_rejects_all(
    client: TestClient,
    auth_headers: dict[str, str],
    db_session: Session,
) -> None:
    # Prompt 40 (AK1): an empty/NULL allowed_models grants NO model (was "blank = all"). The key is
    # created fine but can't be used until it is scoped to a model.
    create_invoice_model_and_table(client, auth_headers, db_session)
    created = create_external_api_key(client, auth_headers, models=None)
    assert created["allowed_models"] in (None, [])  # created OK, just unscoped
    response = client.get("/outbound/invoice", headers={"X-API-Key": created["api_key"]})
    assert response.status_code == 403


def test_ak2_multi_model_allow_list_grants_listed_model(
    client: TestClient,
    auth_headers: dict[str, str],
    db_session: Session,
) -> None:
    # Prompt 40 (AK2): a key scoped to several models can use any model in its list.
    create_invoice_model_and_table(client, auth_headers, db_session)
    api_key = create_external_api_key(client, auth_headers, models=["invoice", "supplier"])["api_key"]
    response = client.get("/outbound/invoice", headers={"X-API-Key": api_key})
    assert response.status_code == 200

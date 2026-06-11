import json

from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from tests.test_data_models import type_a_payload, type_b_payload


def create_sqlite_generated_table(db_session: Session, table_name: str = "dm_invoice") -> None:
    db_session.execute(text("ATTACH DATABASE ':memory:' AS mdp_data"))
    db_session.execute(
        text(
            f"""
            CREATE TABLE mdp_data.{table_name} (
                id TEXT PRIMARY KEY,
                raw_payload TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                invoice_no TEXT,
                amount DOUBLE PRECISION
            )
            """
        )
    )
    db_session.commit()


def create_invoice_model(client: TestClient, auth_headers: dict[str, str]) -> dict:
    response = client.post("/data-models", headers=auth_headers, json=type_a_payload())
    assert response.status_code == 201
    return response.json()


def test_inbound_inserts_valid_record_into_generated_table(
    client: TestClient,
    auth_headers: dict[str, str],
    db_session: Session,
) -> None:
    create_invoice_model(client, auth_headers)
    create_sqlite_generated_table(db_session)

    response = client.post(
        "/inbound/invoice",
        headers=auth_headers,
        json={"invoice_no": "INV-001", "amount": 98.5},
    )
    row = db_session.execute(
        text("SELECT invoice_no, amount FROM mdp_data.dm_invoice")
    ).mappings().one()

    # Envelope (prompt 41): real status 200, code 0, data = the old inbound body.
    assert response.status_code == 200
    assert response.json()["code"] == 0
    assert response.json()["data"]["status"] == "success"
    assert row["invoice_no"] == "INV-001"
    assert row["amount"] == 98.5


def test_required_field_missing_returns_422(
    client: TestClient,
    auth_headers: dict[str, str],
    db_session: Session,
) -> None:
    create_invoice_model(client, auth_headers)
    create_sqlite_generated_table(db_session)

    response = client.post("/inbound/invoice", headers=auth_headers, json={"amount": 98.5})

    assert response.status_code == 422
    assert response.json()["code"] == 1005
    assert response.json()["data"]["errors"][0]["field"] == "invoice_no"


def test_invalid_data_type_returns_422(
    client: TestClient,
    auth_headers: dict[str, str],
    db_session: Session,
) -> None:
    create_invoice_model(client, auth_headers)
    create_sqlite_generated_table(db_session)

    response = client.post(
        "/inbound/invoice",
        headers=auth_headers,
        json={"invoice_no": "INV-001", "amount": "bad"},
    )

    assert response.status_code == 422
    assert response.json()["code"] == 1005
    assert response.json()["data"]["errors"][0]["field"] == "amount"


def test_unknown_field_ignored_for_insert_but_preserved_in_raw_payload(
    client: TestClient,
    auth_headers: dict[str, str],
    db_session: Session,
) -> None:
    create_invoice_model(client, auth_headers)
    create_sqlite_generated_table(db_session)

    response = client.post(
        "/inbound/invoice",
        headers=auth_headers,
        json={"invoice_no": "INV-001", "amount": 98.5, "remark": "extra"},
    )
    row = db_session.execute(
        text("SELECT invoice_no, raw_payload FROM mdp_data.dm_invoice")
    ).mappings().one()
    raw_payload = json.loads(row["raw_payload"])

    assert response.status_code == 200
    assert row["invoice_no"] == "INV-001"
    assert raw_payload["remark"] == "extra"


def test_model_not_found_returns_404(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    response = client.post(
        "/inbound/missing_model",
        headers=auth_headers,
        json={"id": "1"},
    )

    assert response.status_code == 404


def test_type_b_model_inbound_returns_400(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    client.post("/admin/demo/seed-procurement-staging", headers=auth_headers)
    create_response = client.post("/data-models", headers=auth_headers, json=type_b_payload())
    assert create_response.status_code == 201

    response = client.post(
        "/inbound/supplier",
        headers=auth_headers,
        json={"supplier_code": "SUP-001", "supplier_name": "Supplier"},
    )

    assert response.status_code == 400
    assert response.json()["code"] == 1001
    assert response.json()["data"] is None
    assert response.json()["message"] == "Inbound API is only supported for Type A data models"


def test_successful_request_writes_success_transaction(
    client: TestClient,
    auth_headers: dict[str, str],
    db_session: Session,
) -> None:
    create_invoice_model(client, auth_headers)
    create_sqlite_generated_table(db_session)

    client.post(
        "/inbound/invoice",
        headers=auth_headers,
        json={"invoice_no": "INV-001", "amount": 98.5},
    )
    transactions = client.get("/transactions", headers=auth_headers).json()

    assert transactions[0]["status"] == "success"
    assert transactions[0]["direction"] == "inbound"
    assert transactions[0]["protocol"] == "rest"


def test_failed_request_writes_failed_transaction(
    client: TestClient,
    auth_headers: dict[str, str],
    db_session: Session,
) -> None:
    create_invoice_model(client, auth_headers)
    create_sqlite_generated_table(db_session)

    client.post("/inbound/invoice", headers=auth_headers, json={"amount": 98.5})
    transactions = client.get("/transactions", headers=auth_headers).json()

    assert transactions[0]["status"] == "failed"
    assert "invoice_no" in transactions[0]["error_message"]


def test_unauthenticated_inbound_request_fails(client: TestClient) -> None:
    response = client.post("/inbound/invoice", json={"invoice_no": "INV-001"})

    assert response.status_code == 401


def test_get_transactions_requires_authentication(client: TestClient) -> None:
    response = client.get("/transactions")

    assert response.status_code == 401


def test_get_transactions_returns_logged_records(
    client: TestClient,
    auth_headers: dict[str, str],
    db_session: Session,
) -> None:
    create_invoice_model(client, auth_headers)
    create_sqlite_generated_table(db_session)
    client.post(
        "/inbound/invoice",
        headers=auth_headers,
        json={"invoice_no": "INV-001", "amount": 98.5},
    )

    response = client.get("/transactions", headers=auth_headers)

    assert response.status_code == 200
    assert len(response.json()) == 1

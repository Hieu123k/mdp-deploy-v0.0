from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.data_model import DataModel
from tests.test_api_keys import create_external_api_key
from tests.test_data_models import type_a_payload, type_b_payload
from tests.test_inbound import create_sqlite_generated_table
from tests.test_type_b_mapping import purchase_order_summary_payload


def ob(response) -> dict:
    """Unwrap the prompt-41 integration envelope {code,message,data} on /outbound — the old outbound
    body (model/type/count/data/key/…) is now under ``data``."""
    body = response.json()
    return body["data"] if isinstance(body, dict) and {"code", "message", "data"} <= set(body) else body


def create_invoice_model_and_records(
    client: TestClient,
    auth_headers: dict[str, str],
    db_session: Session,
) -> dict:
    model_response = client.post("/data-models", headers=auth_headers, json=type_a_payload())
    assert model_response.status_code == 201
    create_sqlite_generated_table(db_session)
    first = client.post(
        "/inbound/invoice",
        headers=auth_headers,
        json={"invoice_no": "INV-001", "amount": 98.5, "remark": "raw only"},
    )
    second = client.post(
        "/inbound/invoice",
        headers=auth_headers,
        json={"invoice_no": "INV-002", "amount": 125.25},
    )
    assert first.status_code == 200
    assert second.status_code == 200
    return model_response.json()


def supplier_outbound_payload(name: str = "supplier") -> dict:
    payload = type_b_payload(name)
    payload["attributes"].extend(
        [
            {
                "name": "country",
                "display_name": "Country",
                "data_type": "text",
                "source_schema": "mdp_staging",
                "source_table": "stg_jde_supplier",
                "source_column": "country",
            },
            {
                "name": "status",
                "display_name": "Status",
                "data_type": "text",
                "source_schema": "mdp_staging",
                "source_table": "stg_jde_supplier",
                "source_column": "status",
            },
        ]
    )
    return payload


def create_supplier_model(client: TestClient, auth_headers: dict[str, str]) -> dict:
    seed_response = client.post("/admin/demo/seed-procurement-staging", headers=auth_headers)
    assert seed_response.status_code == 200
    create_response = client.post(
        "/data-models",
        headers=auth_headers,
        json=supplier_outbound_payload(),
    )
    assert create_response.status_code == 201
    return create_response.json()


def purchase_order_summary_outbound_payload() -> dict:
    payload = purchase_order_summary_payload()
    payload["attributes"].insert(
        1,
        {
            "name": "po_status",
            "display_name": "PO Status",
            "data_type": "text",
            "source_schema": "mdp_staging",
            "source_table": "vw_jde_purchase_order_summary",
            "source_column": "po_status",
        },
    )
    return payload


def test_outbound_list_returns_records(
    client: TestClient,
    auth_headers: dict[str, str],
    db_session: Session,
) -> None:
    create_invoice_model_and_records(client, auth_headers, db_session)

    response = client.get("/outbound/invoice", headers=auth_headers)

    assert response.status_code == 200
    assert ob(response)["count"] == 2
    assert set(ob(response)["data"][0]) == {"invoice_no", "amount"}


def test_outbound_by_key_returns_one_record(
    client: TestClient,
    auth_headers: dict[str, str],
    db_session: Session,
) -> None:
    create_invoice_model_and_records(client, auth_headers, db_session)

    response = client.get("/outbound/invoice/INV-001", headers=auth_headers)

    assert response.status_code == 200
    assert ob(response)["key"] == "INV-001"
    assert ob(response)["data"]["invoice_no"] == "INV-001"


def test_include_meta_includes_system_columns(
    client: TestClient,
    auth_headers: dict[str, str],
    db_session: Session,
) -> None:
    create_invoice_model_and_records(client, auth_headers, db_session)

    response = client.get("/outbound/invoice?include_meta=true", headers=auth_headers)
    record = ob(response)["data"][0]

    assert response.status_code == 200
    assert "id" in record
    assert "created_at" in record
    assert "updated_at" in record


def test_include_raw_includes_raw_payload(
    client: TestClient,
    auth_headers: dict[str, str],
    db_session: Session,
) -> None:
    create_invoice_model_and_records(client, auth_headers, db_session)

    response = client.get("/outbound/invoice?include_raw=true", headers=auth_headers)
    record = ob(response)["data"][0]

    assert response.status_code == 200
    assert "raw_payload" in record


def test_equality_filter_works(
    client: TestClient,
    auth_headers: dict[str, str],
    db_session: Session,
) -> None:
    create_invoice_model_and_records(client, auth_headers, db_session)

    response = client.get("/outbound/invoice?invoice_no=INV-001", headers=auth_headers)

    assert response.status_code == 200
    assert ob(response)["count"] == 1
    assert ob(response)["data"][0]["invoice_no"] == "INV-001"


def test_invalid_filter_field_returns_422(
    client: TestClient,
    auth_headers: dict[str, str],
    db_session: Session,
) -> None:
    create_invoice_model_and_records(client, auth_headers, db_session)

    response = client.get("/outbound/invoice?raw_payload=x", headers=auth_headers)

    assert response.status_code == 422


def test_model_not_found_returns_404(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    response = client.get("/outbound/missing_model", headers=auth_headers)

    assert response.status_code == 404


def test_type_b_supplier_list_returns_rows(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    create_supplier_model(client, auth_headers)

    response = client.get("/outbound/supplier", headers=auth_headers)

    assert response.status_code == 200
    body = ob(response)
    assert body["type"] == "B"
    assert body["count"] == 5
    assert body["data"][0]["supplier_code"] == "SUP-1001"
    assert "source_table" not in body["data"][0]


def test_type_b_supplier_by_key_returns_one_row(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    create_supplier_model(client, auth_headers)

    response = client.get("/outbound/supplier/SUP-1001", headers=auth_headers)

    assert response.status_code == 200
    body = ob(response)
    assert body["type"] == "B"
    assert body["key"] == "SUP-1001"
    assert body["data"]["supplier_name"] == "ABC Industrial Supplies"


def test_type_b_supplier_filter_works(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    create_supplier_model(client, auth_headers)

    response = client.get("/outbound/supplier?country=VN&status=active", headers=auth_headers)

    assert response.status_code == 200
    assert ob(response)["count"] == 3
    assert {row["country"] for row in ob(response)["data"]} == {"VN"}


def test_type_b_invalid_filter_returns_422(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    create_supplier_model(client, auth_headers)

    response = client.get("/outbound/supplier?source_column=supplier_code", headers=auth_headers)

    assert response.status_code == 422


def test_type_b_include_raw_returns_400(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    create_supplier_model(client, auth_headers)

    response = client.get("/outbound/supplier?include_raw=true", headers=auth_headers)

    assert response.status_code == 400
    assert response.json()["message"] == "include_raw is only supported for Type A models."


def test_no_primary_key_returns_400_for_key_endpoint(
    client: TestClient,
    auth_headers: dict[str, str],
    db_session: Session,
) -> None:
    payload = type_a_payload()
    payload.pop("primary_key")
    for attribute in payload["attributes"]:
        attribute["is_primary_key"] = False
    create_response = client.post("/data-models", headers=auth_headers, json=payload)
    assert create_response.status_code == 201
    create_sqlite_generated_table(db_session)

    response = client.get("/outbound/invoice/INV-001", headers=auth_headers)

    assert response.status_code == 400
    assert response.json()["message"] == "No primary_key configured for this data model"


def test_type_b_no_primary_key_returns_400_for_key_endpoint(
    client: TestClient,
    auth_headers: dict[str, str],
    db_session: Session,
) -> None:
    client.post("/admin/demo/seed-procurement-staging", headers=auth_headers)
    payload = supplier_outbound_payload("supplier_no_pk")
    for attribute in payload["attributes"]:
        attribute["is_primary_key"] = False
    model = DataModel(
        name="supplier_no_pk",
        display_name="Supplier No PK",
        type="B",
        primary_key=None,
        attributes=payload["attributes"],
        status="active",
        sensitivity_level="internal",
        ai_enabled=True,
    )
    db_session.add(model)
    db_session.commit()

    response = client.get("/outbound/supplier_no_pk/SUP-1001", headers=auth_headers)

    assert response.status_code == 400
    assert response.json()["message"] == "No primary_key configured for this data model"


def test_record_not_found_returns_404(
    client: TestClient,
    auth_headers: dict[str, str],
    db_session: Session,
) -> None:
    create_invoice_model_and_records(client, auth_headers, db_session)

    response = client.get("/outbound/invoice/INV-999", headers=auth_headers)

    assert response.status_code == 404


def test_type_b_record_not_found_returns_404(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    create_supplier_model(client, auth_headers)

    response = client.get("/outbound/supplier/SUP-9999", headers=auth_headers)

    assert response.status_code == 404


def test_unauthenticated_outbound_request_fails(client: TestClient) -> None:
    response = client.get("/outbound/invoice")

    assert response.status_code == 401


def test_successful_outbound_query_writes_transaction_log(
    client: TestClient,
    auth_headers: dict[str, str],
    db_session: Session,
) -> None:
    create_invoice_model_and_records(client, auth_headers, db_session)

    client.get("/outbound/invoice", headers=auth_headers)
    response = client.get(
        "/transactions?direction=outbound&status=success",
        headers=auth_headers,
    )

    assert response.status_code == 200
    assert response.json()[0]["status"] == "success"
    assert response.json()[0]["response_payload"]["count"] == 2


def test_type_b_successful_outbound_query_writes_transaction_log(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    create_supplier_model(client, auth_headers)

    client.get("/outbound/supplier", headers=auth_headers)
    response = client.get(
        "/transactions?direction=outbound&status=success",
        headers=auth_headers,
    )

    assert response.status_code == 200
    transaction = response.json()[0]
    assert transaction["status"] == "success"
    assert transaction["response_payload"]["model"] == "supplier"
    assert transaction["response_payload"]["type"] == "B"


def test_failed_outbound_query_writes_transaction_log(
    client: TestClient,
    auth_headers: dict[str, str],
    db_session: Session,
) -> None:
    create_invoice_model_and_records(client, auth_headers, db_session)

    client.get("/outbound/invoice?not_a_field=x", headers=auth_headers)
    response = client.get(
        "/transactions?direction=outbound&status=failed",
        headers=auth_headers,
    )

    assert response.status_code == 200
    assert response.json()[0]["status"] == "failed"
    assert "not_a_field" in response.json()[0]["error_message"]


def test_type_b_failed_outbound_query_writes_transaction_log(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    create_supplier_model(client, auth_headers)

    client.get("/outbound/supplier?not_a_field=x", headers=auth_headers)
    response = client.get(
        "/transactions?direction=outbound&status=failed",
        headers=auth_headers,
    )

    assert response.status_code == 200
    assert response.json()[0]["status"] == "failed"
    assert "not_a_field" in response.json()[0]["error_message"]


def test_outbound_does_not_return_raw_table_columns_by_default(
    client: TestClient,
    auth_headers: dict[str, str],
    db_session: Session,
) -> None:
    create_invoice_model_and_records(client, auth_headers, db_session)

    response = client.get("/outbound/invoice", headers=auth_headers)
    record = ob(response)["data"][0]

    assert "raw_payload" not in record
    assert "id" not in record
    assert "created_at" not in record
    assert "updated_at" not in record


def test_api_key_outbound_works_for_type_b(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    create_supplier_model(client, auth_headers)
    api_key = create_external_api_key(
        client,
        auth_headers,
        directions=["outbound"],
        models=["supplier"],
    )["api_key"]

    response = client.get("/outbound/supplier", headers={"X-API-Key": api_key})

    assert response.status_code == 200
    assert ob(response)["type"] == "B"
    assert ob(response)["count"] == 5


def test_api_key_restricted_to_another_model_cannot_access_type_b(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    create_supplier_model(client, auth_headers)
    api_key = create_external_api_key(
        client,
        auth_headers,
        directions=["outbound"],
        models=["invoice"],
    )["api_key"]

    response = client.get("/outbound/supplier", headers={"X-API-Key": api_key})

    assert response.status_code == 403


def test_purchase_order_summary_view_can_be_queried(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    client.post("/admin/demo/seed-procurement-staging", headers=auth_headers)
    create_response = client.post(
        "/data-models",
        headers=auth_headers,
        json=purchase_order_summary_outbound_payload(),
    )
    assert create_response.status_code == 201

    response = client.get("/outbound/purchase_order_summary?po_status=open", headers=auth_headers)

    assert response.status_code == 200
    assert ob(response)["type"] == "B"
    assert ob(response)["count"] == 2
    assert {row["po_status"] for row in ob(response)["data"]} == {"open"}


def test_purchase_order_summary_view_by_key_returns_summary(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    client.post("/admin/demo/seed-procurement-staging", headers=auth_headers)
    create_response = client.post(
        "/data-models",
        headers=auth_headers,
        json=purchase_order_summary_outbound_payload(),
    )
    assert create_response.status_code == 201

    response = client.get(
        "/outbound/purchase_order_summary/PO-2026-0001",
        headers=auth_headers,
    )

    assert response.status_code == 200
    data = ob(response)["data"]
    assert data["po_no"] == "PO-2026-0001"
    assert data["supplier_name"] == "ABC Industrial Supplies"
    assert data["line_count"] == 2

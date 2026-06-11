from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session


def _qualified(db_session: Session, table_name: str) -> str:
    if db_session.bind.dialect.name == "postgresql":
        return f"mdp_staging.{table_name}"
    return table_name


def _attribute(
    name: str,
    data_type: str,
    *,
    source_table: str,
    source_column: str | None = None,
    primary_key: bool = False,
    required: bool = False,
) -> dict:
    return {
        "name": name,
        "display_name": name.replace("_", " ").title(),
        "data_type": data_type,
        "required": required,
        "source_schema": "mdp_staging",
        "source_table": source_table,
        "source_column": source_column or name,
        "is_primary_key": primary_key,
    }


def supplier_smoke_payload(name: str = "supplier_smoke") -> dict:
    return {
        "name": name,
        "display_name": "Supplier Smoke",
        "type": "B",
        "category": "procurement",
        "namespace": f"avenue.demo.procurement.{name}",
        "domain": "procurement",
        "entity_type": "supplier",
        "business_process": "procure_to_pay",
        "source_layer": "staging",
        "canonical_status": "canonical",
        "site_scope": "enterprise",
        "source_system": "JDE ERP",
        "owner_department": "Procurement",
        "primary_key": "supplier_code",
        "attributes": [
            _attribute(
                "supplier_code",
                "text",
                source_table="stg_jde_supplier",
                primary_key=True,
                required=True,
            ),
            _attribute("supplier_name", "text", source_table="stg_jde_supplier"),
            _attribute("tax_code", "text", source_table="stg_jde_supplier"),
            _attribute("supplier_type", "text", source_table="stg_jde_supplier"),
            _attribute("country", "text", source_table="stg_jde_supplier"),
            _attribute("city", "text", source_table="stg_jde_supplier"),
            _attribute("status", "text", source_table="stg_jde_supplier"),
        ],
    }


def purchase_order_summary_smoke_payload(
    name: str = "purchase_order_summary_smoke",
) -> dict:
    source_table = "vw_jde_purchase_order_summary"
    return {
        "name": name,
        "display_name": "Purchase Order Summary Smoke",
        "type": "B",
        "category": "procurement",
        "namespace": f"avenue.demo.procurement.{name}",
        "domain": "procurement",
        "entity_type": "purchase_order",
        "business_process": "procure_to_pay",
        "source_layer": "curated_view",
        "canonical_status": "curated",
        "site_scope": "enterprise",
        "source_system": "JDE ERP",
        "owner_department": "Procurement",
        "primary_key": "po_no",
        "attributes": [
            _attribute("po_no", "text", source_table=source_table, primary_key=True, required=True),
            _attribute("supplier_code", "text", source_table=source_table),
            _attribute("supplier_name", "text", source_table=source_table),
            _attribute("buyer_name", "text", source_table=source_table),
            _attribute("company_code", "text", source_table=source_table),
            _attribute("branch_plant", "text", source_table=source_table),
            _attribute("order_date", "date", source_table=source_table),
            _attribute("currency", "text", source_table=source_table),
            _attribute("po_status", "text", source_table=source_table),
            _attribute("total_amount", "float", source_table=source_table),
            _attribute("line_count", "integer", source_table=source_table),
            _attribute("total_ordered_quantity", "float", source_table=source_table),
            _attribute("total_received_quantity", "float", source_table=source_table),
            _attribute("open_line_count", "integer", source_table=source_table),
            _attribute("invoice_count", "integer", source_table=source_table),
            _attribute("total_invoice_amount", "float", source_table=source_table),
            _attribute("total_open_invoice_amount", "float", source_table=source_table),
            _attribute("payment_status_summary", "text", source_table=source_table),
            _attribute(
                "source_updated_at",
                "datetime",
                source_table=source_table,
                source_column="updated_at",
            ),
        ],
    }


def create_api_key(
    client: TestClient,
    auth_headers: dict[str, str],
    *,
    name: str,
    directions: list[str],
    models: list[str] | None,
) -> str:
    response = client.post(
        "/api-keys",
        headers=auth_headers,
        json={
            "name": name,
            "description": "Smoke test API key",
            "source_system": "External Test Client",
            "allowed_directions": directions,
            "allowed_models": models,
        },
    )
    assert response.status_code == 201
    return response.json()["api_key"]


def seed_demo_data(client: TestClient, auth_headers: dict[str, str]) -> None:
    response = client.post("/admin/demo/seed-procurement-staging", headers=auth_headers)
    assert response.status_code == 200


def create_smoke_models(client: TestClient, auth_headers: dict[str, str]) -> None:
    supplier_response = client.post(
        "/data-models",
        headers=auth_headers,
        json=supplier_smoke_payload(),
    )
    po_response = client.post(
        "/data-models",
        headers=auth_headers,
        json=purchase_order_summary_smoke_payload(),
    )
    assert supplier_response.status_code == 201
    assert po_response.status_code == 201


def test_smoke_health_auth_and_protected_endpoint(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    health = client.get("/health")
    login = client.post("/auth/login", json={"username": "admin", "password": "admin123"})
    me = client.get("/auth/me", headers=auth_headers)
    protected = client.get("/data-models")

    assert health.status_code == 200
    assert health.json() == {
        "status": "ok",
        "service": "manufacturing-data-platform",
    }
    assert login.status_code == 200
    assert login.json()["access_token"]
    assert me.status_code == 200
    assert me.json()["username"] == "admin"
    assert protected.status_code == 401


def test_smoke_seeded_procurement_staging_data(
    client: TestClient,
    auth_headers: dict[str, str],
    db_session: Session,
) -> None:
    seed_demo_data(client, auth_headers)

    supplier = db_session.execute(
        text(
            f"SELECT supplier_name FROM {_qualified(db_session, 'stg_jde_supplier')} "
            "WHERE supplier_code = :supplier_code"
        ),
        {"supplier_code": "SUP-1001"},
    ).scalar_one()
    po = db_session.execute(
        text(
            f"SELECT supplier_code FROM {_qualified(db_session, 'stg_jde_po_header')} "
            "WHERE po_no = :po_no"
        ),
        {"po_no": "PO-2026-0001"},
    ).scalar_one()
    view_row = db_session.execute(
        text(
            f"SELECT supplier_name FROM {_qualified(db_session, 'vw_jde_purchase_order_summary')} "
            "WHERE po_no = :po_no"
        ),
        {"po_no": "PO-2026-0001"},
    ).scalar_one()

    assert supplier == "ABC Industrial Supplies"
    assert po == "SUP-1001"
    assert view_row == "ABC Industrial Supplies"


def test_smoke_type_b_supplier_flow(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    seed_demo_data(client, auth_headers)
    payload = supplier_smoke_payload()

    validate = client.post("/data-models/type-b/validate-mapping", headers=auth_headers, json=payload)
    preview = client.post("/data-models/type-b/preview", headers=auth_headers, json=payload)
    save = client.post("/data-models", headers=auth_headers, json=payload)
    by_key = client.get("/outbound/supplier_smoke/SUP-1001", headers=auth_headers)
    filtered = client.get("/outbound/supplier_smoke?country=VN", headers=auth_headers)

    assert validate.status_code == 200
    assert preview.status_code == 200
    assert any(row["supplier_code"] == "SUP-1001" for row in preview.json()["data"])
    assert save.status_code == 201
    assert by_key.status_code == 200
    assert by_key.json()["data"]["data"]["supplier_name"] == "ABC Industrial Supplies"
    assert filtered.status_code == 200
    assert any(row["supplier_code"] == "SUP-1001" for row in filtered.json()["data"]["data"])
    assert {row["country"] for row in filtered.json()["data"]["data"]} == {"VN"}


def test_smoke_type_b_purchase_order_summary_flow(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    seed_demo_data(client, auth_headers)
    payload = purchase_order_summary_smoke_payload()

    validate = client.post("/data-models/type-b/validate-mapping", headers=auth_headers, json=payload)
    save = client.post("/data-models", headers=auth_headers, json=payload)
    by_key = client.get(
        "/outbound/purchase_order_summary_smoke/PO-2026-0001",
        headers=auth_headers,
    )
    filtered = client.get(
        "/outbound/purchase_order_summary_smoke?po_status=open",
        headers=auth_headers,
    )

    assert validate.status_code == 200
    assert validate.json()["status"] == "success"
    assert save.status_code == 201
    assert by_key.status_code == 200
    data = by_key.json()["data"]["data"]
    assert data["po_no"] == "PO-2026-0001"
    assert data["supplier_code"] == "SUP-1001"
    assert data["supplier_name"] == "ABC Industrial Supplies"
    assert data["po_status"] == "open"
    assert filtered.status_code == 200
    assert any(row["po_no"] == "PO-2026-0001" for row in filtered.json()["data"]["data"])
    assert {row["po_status"] for row in filtered.json()["data"]["data"]} == {"open"}


def test_smoke_api_key_scope_for_type_b_outbound(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    seed_demo_data(client, auth_headers)
    create_smoke_models(client, auth_headers)

    both_key = create_api_key(
        client,
        auth_headers,
        name="smoke both outbound",
        directions=["outbound"],
        models=["supplier_smoke", "purchase_order_summary_smoke"],
    )
    supplier_key = create_api_key(
        client,
        auth_headers,
        name="smoke supplier outbound",
        directions=["outbound"],
        models=["supplier_smoke"],
    )
    inbound_only_key = create_api_key(
        client,
        auth_headers,
        name="smoke inbound only",
        directions=["inbound"],
        models=["supplier_smoke", "purchase_order_summary_smoke"],
    )

    assert client.get(
        "/outbound/supplier_smoke/SUP-1001",
        headers={"X-API-Key": both_key},
    ).status_code == 200
    assert client.get(
        "/outbound/purchase_order_summary_smoke/PO-2026-0001",
        headers={"X-API-Key": both_key},
    ).status_code == 200
    assert client.get(
        "/outbound/supplier_smoke/SUP-1001",
        headers={"X-API-Key": supplier_key},
    ).status_code == 200
    assert client.get(
        "/outbound/purchase_order_summary_smoke/PO-2026-0001",
        headers={"X-API-Key": supplier_key},
    ).status_code == 403
    assert client.get(
        "/outbound/supplier_smoke/SUP-1001",
        headers={"X-API-Key": inbound_only_key},
    ).status_code == 403


def test_smoke_transaction_logging_and_negative_outbound_cases(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    seed_demo_data(client, auth_headers)
    create_smoke_models(client, auth_headers)

    success = client.get("/outbound/supplier_smoke/SUP-1001", headers=auth_headers)
    invalid_filter = client.get("/outbound/supplier_smoke?not_a_field=x", headers=auth_headers)
    include_raw = client.get("/outbound/supplier_smoke?include_raw=true", headers=auth_headers)
    unknown = client.get("/outbound/unknown_model", headers=auth_headers)
    other_model_key = create_api_key(
        client,
        auth_headers,
        name="smoke other model",
        directions=["outbound"],
        models=["invoice"],
    )
    restricted = client.get("/outbound/supplier_smoke/SUP-1001", headers={"X-API-Key": other_model_key})

    transactions = client.get("/transactions?direction=outbound&limit=100", headers=auth_headers)
    transaction_rows = transactions.json()

    assert success.status_code == 200
    assert invalid_filter.status_code == 422
    assert include_raw.status_code == 400
    assert unknown.status_code == 404
    assert restricted.status_code == 403
    assert transactions.status_code == 200
    assert any(
        row["status"] == "success"
        and row["auth_type"] == "jwt"
        and "/outbound/supplier_smoke" in (row["endpoint"] or "")
        for row in transaction_rows
    )
    assert any(
        row["status"] == "failed"
        and "/outbound/supplier_smoke" in (row["endpoint"] or "")
        for row in transaction_rows
    )

from fastapi.testclient import TestClient

from tests.test_data_models import type_b_payload


def seed_staging(client: TestClient, auth_headers: dict[str, str]) -> None:
    response = client.post("/admin/demo/seed-procurement-staging", headers=auth_headers)
    assert response.status_code == 200


def purchase_order_summary_payload() -> dict:
    return {
        "name": "purchase_order_summary",
        "display_name": "Purchase Order Summary",
        "type": "B",
        "category": "procurement",
        "description": "Curated purchase order summary from JDE staging data",
        "source_system": "JDE ERP",
        "primary_key": "po_no",
        "attributes": [
            {
                "name": "po_no",
                "display_name": "Purchase Order Number",
                "data_type": "text",
                "required": True,
                "source_schema": "mdp_staging",
                "source_table": "vw_jde_purchase_order_summary",
                "source_column": "po_no",
                "is_primary_key": True,
            },
            {
                "name": "supplier_name",
                "display_name": "Supplier Name",
                "data_type": "text",
                "source_schema": "mdp_staging",
                "source_table": "vw_jde_purchase_order_summary",
                "source_column": "supplier_name",
            },
            {
                "name": "line_count",
                "display_name": "Line Count",
                "data_type": "integer",
                "source_schema": "mdp_staging",
                "source_table": "vw_jde_purchase_order_summary",
                "source_column": "line_count",
            },
            {
                "name": "payment_status_summary",
                "display_name": "Payment Status Summary",
                "data_type": "text",
                "source_schema": "mdp_staging",
                "source_table": "vw_jde_purchase_order_summary",
                "source_column": "payment_status_summary",
            },
        ],
    }


def test_create_valid_type_b_supplier_model(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    seed_staging(client, auth_headers)

    response = client.post("/data-models", headers=auth_headers, json=type_b_payload())

    assert response.status_code == 201
    body = response.json()
    assert body["type"] == "B"
    assert body["generated_table"] is None
    assert body["source_schema"] == "mdp_staging"
    assert body["source_table"] == "stg_jde_supplier"


def test_validate_mapping_success(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    seed_staging(client, auth_headers)

    response = client.post(
        "/data-models/type-b/validate-mapping",
        headers=auth_headers,
        json=type_b_payload(),
    )

    assert response.status_code == 200
    assert response.json()["status"] == "success"
    assert response.json()["mapped_columns"][0]["source_column"] == "supplier_code"


def test_attribute_name_can_differ_from_source_column(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    seed_staging(client, auth_headers)
    payload = type_b_payload()
    payload["name"] = "supplier_alias"
    payload["primary_key"] = "supplier_no"
    payload["attributes"][0]["name"] = "supplier_no"

    validate_response = client.post(
        "/data-models/type-b/validate-mapping",
        headers=auth_headers,
        json=payload,
    )
    preview_response = client.post(
        "/data-models/type-b/preview",
        headers=auth_headers,
        json=payload,
    )

    assert validate_response.status_code == 200
    assert validate_response.json()["mapped_columns"][0]["attribute"] == "supplier_no"
    assert validate_response.json()["mapped_columns"][0]["source_column"] == "supplier_code"
    assert preview_response.status_code == 200
    assert preview_response.json()["data"][0]["supplier_no"] == "SUP-1001"
    assert "supplier_code" not in preview_response.json()["data"][0]


def test_validate_mapping_fails_when_source_table_missing(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    seed_staging(client, auth_headers)
    payload = type_b_payload()
    payload["attributes"][0]["source_table"] = "missing_table"
    payload["attributes"][1]["source_table"] = "missing_table"

    response = client.post(
        "/data-models/type-b/validate-mapping",
        headers=auth_headers,
        json=payload,
    )

    assert response.status_code == 422
    assert "Table not found" in str(response.json()["detail"])


def test_validate_mapping_fails_when_source_column_missing(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    seed_staging(client, auth_headers)
    payload = type_b_payload()
    payload["attributes"][0]["source_column"] = "missing_column"

    response = client.post(
        "/data-models/type-b/validate-mapping",
        headers=auth_headers,
        json=payload,
    )

    assert response.status_code == 422
    assert "Source column not found" in str(response.json()["detail"])


def test_validate_mapping_fails_when_source_column_not_configured(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    seed_staging(client, auth_headers)
    payload = type_b_payload()
    payload["attributes"][0].pop("source_column")

    response = client.post(
        "/data-models/type-b/validate-mapping",
        headers=auth_headers,
        json=payload,
    )

    assert response.status_code == 422
    assert "Type B attributes require source_column" in str(response.json()["detail"])


def test_validate_mapping_fails_for_invalid_identifier(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    payload = type_b_payload()
    payload["attributes"][0]["source_schema"] = "mdp_staging;"

    response = client.post(
        "/data-models/type-b/validate-mapping",
        headers=auth_headers,
        json=payload,
    )

    assert response.status_code == 422


def test_validate_mapping_fails_for_multiple_source_tables(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    seed_staging(client, auth_headers)
    payload = type_b_payload()
    payload["attributes"][1]["source_table"] = "stg_jde_po_header"
    payload["attributes"][1]["source_column"] = "po_no"

    response = client.post(
        "/data-models/type-b/validate-mapping",
        headers=auth_headers,
        json=payload,
    )

    assert response.status_code == 422
    assert "only one source table" in str(response.json()["detail"])


def test_validate_mapping_fails_for_incompatible_data_type(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    seed_staging(client, auth_headers)
    payload = type_b_payload()
    payload["attributes"][0]["data_type"] = "integer"

    response = client.post(
        "/data-models/type-b/validate-mapping",
        headers=auth_headers,
        json=payload,
    )

    assert response.status_code == 422
    assert "incompatible" in str(response.json()["detail"])


def test_preview_unsaved_type_b_mapping_returns_supplier_rows(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    seed_staging(client, auth_headers)

    response = client.post(
        "/data-models/type-b/preview",
        headers=auth_headers,
        json=type_b_payload(),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 5
    assert body["data"][0]["supplier_code"] == "SUP-1001"


def test_preview_saved_type_b_model_returns_supplier_rows(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    seed_staging(client, auth_headers)
    create_response = client.post("/data-models", headers=auth_headers, json=type_b_payload())
    data_model_id = create_response.json()["id"]

    response = client.get(
        f"/data-models/{data_model_id}/mapped-preview",
        headers=auth_headers,
    )

    assert response.status_code == 200
    assert response.json()["data"][0]["supplier_name"] == "ABC Industrial Supplies"


def test_type_b_requires_primary_key(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    seed_staging(client, auth_headers)
    payload = type_b_payload()
    payload["primary_key"] = None
    payload["attributes"][0]["is_primary_key"] = False

    response = client.post("/data-models", headers=auth_headers, json=payload)

    assert response.status_code == 422
    assert "primary_key" in str(response.json()["detail"])


def test_type_b_primary_key_must_reference_valid_mapping(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    seed_staging(client, auth_headers)
    payload = type_b_payload()
    payload["attributes"][0]["source_column"] = "missing_column"

    response = client.post("/data-models", headers=auth_headers, json=payload)

    assert response.status_code == 422
    assert "Primary key attribute must map to an existing compatible source_column" in str(
        response.json()["detail"]
    )


def test_type_b_primary_key_source_column_nullable_returns_warning(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    seed_staging(client, auth_headers)
    payload = type_b_payload()
    payload["primary_key"] = "country"
    payload["attributes"][0]["is_primary_key"] = False
    payload["attributes"][1] = {
        "name": "country",
        "display_name": "Country",
        "data_type": "text",
        "source_schema": "mdp_staging",
        "source_table": "stg_jde_supplier",
        "source_column": "country",
    }

    response = client.post(
        "/data-models/type-b/validate-mapping",
        headers=auth_headers,
        json=payload,
    )

    assert response.status_code == 200
    warnings = response.json()["warnings"]
    assert {
        "field": "primary_key",
        "message": "Primary key source column is nullable. Ensure values are unique and not null.",
    } in warnings


def test_validate_mapping_view_primary_key_nullable_returns_warning(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    seed_staging(client, auth_headers)

    response = client.post(
        "/data-models/type-b/validate-mapping",
        headers=auth_headers,
        json=purchase_order_summary_payload(),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["source_table"] == "vw_jde_purchase_order_summary"
    assert {
        "field": "primary_key",
        "message": (
            "Primary key source column is from a view. Nullability cannot be reliably "
            "enforced by information_schema."
        ),
    } in body["warnings"]


def test_purchase_order_summary_view_preview_returns_rows(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    seed_staging(client, auth_headers)

    response = client.post(
        "/data-models/type-b/preview",
        headers=auth_headers,
        json=purchase_order_summary_payload(),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 5
    assert body["warnings"]
    first_po = next(row for row in body["data"] if row["po_no"] == "PO-2026-0001")
    assert first_po["supplier_name"] == "ABC Industrial Supplies"
    assert first_po["line_count"] == 2


def test_type_b_requests_require_authentication(client: TestClient) -> None:
    validate_response = client.post(
        "/data-models/type-b/validate-mapping",
        json=type_b_payload(),
    )
    preview_response = client.post(
        "/data-models/type-b/preview",
        json=type_b_payload(),
    )

    assert validate_response.status_code == 401
    assert preview_response.status_code == 401

from fastapi.testclient import TestClient


def seed_staging(client: TestClient, auth_headers: dict[str, str]) -> None:
    response = client.post("/admin/demo/seed-procurement-staging", headers=auth_headers)
    assert response.status_code == 200, response.text


def test_list_data_model_templates(client: TestClient, auth_headers: dict[str, str]) -> None:
    response = client.get("/data-model-templates", headers=auth_headers)

    assert response.status_code == 200, response.text
    templates = response.json()
    keys = {template["template_key"] for template in templates}
    assert "jde_supplier" in keys
    assert "jde_purchase_order_summary" in keys
    assert "jde_po_line" in keys


def test_get_jde_supplier_data_model_template(client: TestClient, auth_headers: dict[str, str]) -> None:
    response = client.get("/data-model-templates/jde_supplier", headers=auth_headers)

    assert response.status_code == 200, response.text
    template = response.json()
    assert template["model_name"] == "supplier"
    assert template["model_type"] == "B"
    assert template["primary_key"] == "supplier_code"
    assert template["source_schema"] == "mdp_staging"
    assert template["source_table"] == "stg_jde_supplier"
    assert template["related_migration_template_key"] == "jde_supplier_master"


def test_create_supplier_model_from_template(client: TestClient, auth_headers: dict[str, str]) -> None:
    seed_staging(client, auth_headers)

    response = client.post(
        "/data-model-templates/jde_supplier/create-model",
        headers=auth_headers,
        json={"name": "supplier_template_test", "display_name": "Supplier Template Test"},
    )

    assert response.status_code == 201, response.text
    body = response.json()
    model = body["data_model"]
    assert body["status"] == "success"
    assert model["name"] == "supplier_template_test"
    assert model["type"] == "B"
    assert model["source_schema"] == "mdp_staging"
    assert model["source_table"] == "stg_jde_supplier"
    assert model["primary_key"] == "supplier_code"
    assert model["domain"] == "procurement"
    assert model["canonical_status"] == "canonical"


def test_create_purchase_order_summary_model_from_template(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    seed_staging(client, auth_headers)

    response = client.post(
        "/data-model-templates/jde_purchase_order_summary/create-model",
        headers=auth_headers,
        json={"name": "po_summary_template_test"},
    )

    assert response.status_code == 201, response.text
    model = response.json()["data_model"]
    assert model["name"] == "po_summary_template_test"
    assert model["source_table"] == "vw_jde_purchase_order_summary"
    assert model["primary_key"] == "po_no"
    assert model["source_layer"] == "curated_view"
    assert model["canonical_status"] == "curated"


def test_duplicate_template_model_name_returns_409(client: TestClient, auth_headers: dict[str, str]) -> None:
    seed_staging(client, auth_headers)
    first = client.post("/data-model-templates/jde_supplier/create-model", headers=auth_headers, json={})
    assert first.status_code == 201, first.text

    duplicate = client.post("/data-model-templates/jde_supplier/create-model", headers=auth_headers, json={})

    assert duplicate.status_code == 409
    assert duplicate.json()["detail"] == "Data model name already exists"


def test_template_create_model_missing_source_table_returns_422(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    seed_staging(client, auth_headers)

    response = client.post(
        "/data-model-templates/jde_supplier/create-model",
        headers=auth_headers,
        json={"name": "supplier_missing_source_test", "source_table": "stg_missing_supplier"},
    )

    assert response.status_code == 422


def test_data_model_templates_require_auth(client: TestClient) -> None:
    assert client.get("/data-model-templates").status_code == 401
    assert client.get("/data-model-templates/jde_supplier").status_code == 401
    assert client.post("/data-model-templates/jde_supplier/create-model", json={}).status_code == 401

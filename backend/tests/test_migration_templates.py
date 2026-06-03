from fastapi.testclient import TestClient


def test_list_migration_templates(client: TestClient, auth_headers: dict[str, str]) -> None:
    response = client.get("/migration-templates", headers=auth_headers)

    assert response.status_code == 200, response.text
    templates = response.json()
    keys = {template["template_key"] for template in templates}
    assert "jde_supplier_master" in keys
    assert "jde_purchase_order_summary_view" in keys
    assert all(template["group"] == "JDE Procurement" for template in templates)


def test_get_jde_supplier_template(client: TestClient, auth_headers: dict[str, str]) -> None:
    response = client.get("/migration-templates/jde_supplier_master", headers=auth_headers)

    assert response.status_code == 200, response.text
    template = response.json()
    assert template["display_name"] == "JDE Supplier Master"
    assert template["source_table"] == "F0101"
    assert template["related_source_tables"] == ["F0401"]
    assert template["target_schema"] == "mdp_staging"
    assert template["target_table"] == "stg_jde_supplier"
    assert template["primary_key_columns"] == ["supplier_code"]
    assert template["watermark_column"] == "updated_at"
    assert template["config"]["jde_source_watermark_column"] == "UPMJ"


def test_create_migration_job_from_template(client: TestClient, auth_headers: dict[str, str]) -> None:
    response = client.post(
        "/migration-templates/jde_supplier_master/create-job",
        headers=auth_headers,
        json={"name": "migrate_supplier_from_template_test"},
    )

    assert response.status_code == 201, response.text
    job = response.json()
    assert job["name"] == "migrate_supplier_from_template_test"
    assert job["source_system"] == "JDE Oracle"
    assert job["source_type"] == "oracle"
    assert job["migration_tool"] == "ora2pg"
    assert job["source_schema"] == "PRODDTA"
    assert job["source_table"] == "F0101"
    assert job["target_schema"] == "mdp_staging"
    assert job["target_table"] == "stg_jde_supplier"
    assert job["load_mode"] == "external_bulk"
    assert job["incremental_strategy"] == "greater_than_last_watermark"
    assert job["watermark_column"] == "updated_at"
    assert job["watermark_column_type"] == "datetime"
    assert job["validation_level"] == "key_integrity"
    assert job["config"]["ora2pg_project"] == "jde_supplier_master"
    assert job["config"]["jde_source_watermark_column"] == "UPMJ"


def test_duplicate_generated_template_job_name_returns_409(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    first = client.post("/migration-templates/jde_po_header/create-job", headers=auth_headers, json={})
    assert first.status_code == 201, first.text

    duplicate = client.post("/migration-templates/jde_po_header/create-job", headers=auth_headers, json={})

    assert duplicate.status_code == 409
    assert duplicate.json()["detail"] == "Migration job name is already registered"


def test_template_create_job_allows_overrides(client: TestClient, auth_headers: dict[str, str]) -> None:
    response = client.post(
        "/migration-templates/jde_po_line/create-job",
        headers=auth_headers,
        json={
            "name": "migrate_po_line_crpdta",
            "source_schema": "CRPDTA",
            "target_table": "stg_jde_po_line_uat",
            "estimated_rows": 12345,
            "estimated_size_gb": 1.5,
            "config": {"customer_environment": "uat"},
        },
    )

    assert response.status_code == 201, response.text
    job = response.json()
    assert job["source_schema"] == "CRPDTA"
    assert job["target_table"] == "stg_jde_po_line_uat"
    assert job["estimated_rows"] == 12345
    assert job["estimated_size_gb"] == 1.5
    assert job["config"]["customer_environment"] == "uat"
    assert job["config"]["ora2pg_project"] == "jde_po_line"


def test_unknown_template_returns_404(client: TestClient, auth_headers: dict[str, str]) -> None:
    response = client.get("/migration-templates/not_real", headers=auth_headers)

    assert response.status_code == 404


def test_migration_templates_require_auth(client: TestClient) -> None:
    assert client.get("/migration-templates").status_code == 401
    assert client.get("/migration-templates/jde_supplier_master").status_code == 401
    assert client.post("/migration-templates/jde_supplier_master/create-job", json={}).status_code == 401

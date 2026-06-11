from fastapi.testclient import TestClient

from app.services.table_generator import create_generated_table_for_model


def type_a_payload(name: str = "invoice") -> dict:
    return {
        "name": name,
        "display_name": "Invoice",
        "type": "A",
        "category": "finance",
        "description": "Invoice data received from external systems",
        "business_definition": "A commercial document issued by a supplier for payment",
        "owner_department": "Finance",
        "source_system": "External API",
        "primary_key": "invoice_no",
        "sensitivity_level": "internal",
        "ai_enabled": True,
        "attributes": [
            {
                "name": "invoice_no",
                "display_name": "Invoice Number",
                "data_type": "text",
                "required": True,
                "description": "Unique invoice number",
                "source_path": "$.invoice_no",
                "is_primary_key": True,
                "sensitivity": "internal",
                "synonyms": ["invoice id", "invoice code"],
            },
            {
                "name": "amount",
                "display_name": "Amount",
                "data_type": "float",
                "required": True,
                "description": "Invoice amount",
                "source_path": "$.amount",
                "sensitivity": "confidential",
            },
        ],
    }


def type_b_payload(name: str = "supplier") -> dict:
    return {
        "name": name,
        "display_name": "Supplier",
        "type": "B",
        "category": "procurement",
        "description": "Supplier master data linked from JDE staging table",
        "business_definition": "A business entity that provides goods or services",
        "owner_department": "Procurement",
        "source_system": "JDE ERP",
        "primary_key": "supplier_code",
        "sensitivity_level": "internal",
        "ai_enabled": True,
        "attributes": [
            {
                "name": "supplier_code",
                "display_name": "Supplier Code",
                "data_type": "text",
                "required": True,
                "description": "Supplier code from JDE Address Book",
                "source_schema": "mdp_staging",
                "source_table": "stg_jde_supplier",
                "source_column": "supplier_code",
                "is_primary_key": True,
                "sensitivity": "internal",
                "synonyms": ["vendor code", "supplier id"],
            },
            {
                "name": "supplier_name",
                "display_name": "Supplier Name",
                "data_type": "text",
                "required": True,
                "description": "Supplier name from JDE Address Book",
                "source_schema": "mdp_staging",
                "source_table": "stg_jde_supplier",
                "source_column": "supplier_name",
                "sensitivity": "internal",
                "synonyms": ["vendor name"],
            },
        ],
    }


def test_create_type_a_data_model(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    response = client.post("/data-models", headers=auth_headers, json=type_a_payload())

    assert response.status_code == 201
    assert response.json()["name"] == "invoice"
    assert response.json()["type"] == "A"
    assert response.json()["generated_table"] == "mdp_data.dm_invoice"


def test_create_type_b_data_model(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    client.post("/admin/demo/seed-procurement-staging", headers=auth_headers)
    response = client.post("/data-models", headers=auth_headers, json=type_b_payload())

    assert response.status_code == 201
    assert response.json()["name"] == "supplier"
    assert response.json()["type"] == "B"
    assert response.json()["generated_table"] is None
    assert response.json()["source_schema"] == "mdp_staging"
    assert response.json()["source_table"] == "stg_jde_supplier"


def test_list_data_models(client: TestClient, auth_headers: dict[str, str]) -> None:
    client.post("/data-models", headers=auth_headers, json=type_a_payload())

    response = client.get("/data-models", headers=auth_headers)

    assert response.status_code == 200
    assert len(response.json()) == 1


def test_create_data_model_with_classification_fields(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    payload = type_a_payload(name="quality_result")
    payload.update(
        {
            "namespace": "avenue.demo.quality.quality_result",
            "domain": "quality",
            "entity_type": "quality_result",
            "business_process": "quality_management",
            "source_layer": "external_api",
            "canonical_status": "source_aligned",
            "site_scope": "site",
        }
    )

    response = client.post("/data-models", headers=auth_headers, json=payload)

    assert response.status_code == 201
    data = response.json()
    assert data["namespace"] == "avenue.demo.quality.quality_result"
    assert data["domain"] == "quality"
    assert data["entity_type"] == "quality_result"
    assert data["business_process"] == "quality_management"
    assert data["source_layer"] == "external_api"
    assert data["canonical_status"] == "source_aligned"
    assert data["site_scope"] == "site"


def test_invalid_namespace_fails(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    payload = type_a_payload()
    payload["namespace"] = "Avenue.Demo.Procurement.Supplier"

    response = client.post("/data-models", headers=auth_headers, json=payload)

    assert response.status_code == 422


def test_data_model_domain_filter(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    procurement_payload = type_a_payload(name="procurement_invoice")
    procurement_payload["category"] = "procurement"
    procurement_payload["domain"] = "procurement"
    finance_payload = type_a_payload(name="finance_invoice")
    finance_payload["domain"] = "finance"

    client.post("/data-models", headers=auth_headers, json=procurement_payload)
    client.post("/data-models", headers=auth_headers, json=finance_payload)

    response = client.get("/data-models?domain=procurement", headers=auth_headers)

    assert response.status_code == 200
    assert [model["name"] for model in response.json()] == ["procurement_invoice"]


def test_data_model_classification_defaults(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    payload = type_a_payload(name="purchase_invoice")
    payload["category"] = "procurement"

    response = client.post("/data-models", headers=auth_headers, json=payload)

    assert response.status_code == 201
    data = response.json()
    assert data["domain"] == "procurement"
    assert data["source_layer"] == "generated_table"
    assert data["canonical_status"] == "experimental"
    assert data["site_scope"] == "enterprise"


def test_type_b_source_layer_default_from_source_table(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    client.post("/admin/demo/seed-procurement-staging", headers=auth_headers)

    response = client.post(
        "/data-models",
        headers=auth_headers,
        json=type_b_payload(name="supplier_linked"),
    )

    assert response.status_code == 201
    assert response.json()["source_layer"] == "staging"


def test_get_data_model_by_id(client: TestClient, auth_headers: dict[str, str]) -> None:
    create_response = client.post("/data-models", headers=auth_headers, json=type_a_payload())
    data_model_id = create_response.json()["id"]

    response = client.get(f"/data-models/{data_model_id}", headers=auth_headers)

    assert response.status_code == 200
    assert response.json()["id"] == data_model_id


def test_update_data_model(client: TestClient, auth_headers: dict[str, str]) -> None:
    create_response = client.post("/data-models", headers=auth_headers, json=type_a_payload())
    data_model_id = create_response.json()["id"]

    response = client.put(
        f"/data-models/{data_model_id}",
        headers=auth_headers,
        json={"display_name": "Supplier Invoice", "category": "accounts_payable"},
    )

    assert response.status_code == 200
    assert response.json()["display_name"] == "Supplier Invoice"
    assert response.json()["category"] == "accounts_payable"


def test_deactivate_data_model(client: TestClient, auth_headers: dict[str, str]) -> None:
    create_response = client.post("/data-models", headers=auth_headers, json=type_a_payload())
    data_model_id = create_response.json()["id"]

    response = client.delete(f"/data-models/{data_model_id}", headers=auth_headers)

    assert response.status_code == 200
    assert response.json()["status"] == "inactive"
    assert response.json()["generated_table"] == "mdp_data.dm_invoice"


def test_invalid_model_name_fails(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    payload = type_a_payload(name="Invoice")

    response = client.post("/data-models", headers=auth_headers, json=payload)

    assert response.status_code == 422


def test_invalid_attribute_name_fails(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    payload = type_a_payload()
    payload["attributes"][0]["name"] = "InvoiceNo"

    response = client.post("/data-models", headers=auth_headers, json=payload)

    assert response.status_code == 422


def test_system_column_conflict_fails(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    payload = type_a_payload()
    payload["attributes"][0]["name"] = "created_at"
    payload["primary_key"] = "created_at"

    response = client.post("/data-models", headers=auth_headers, json=payload)

    assert response.status_code == 422


def test_invalid_data_type_fails(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    payload = type_a_payload()
    payload["attributes"][0]["data_type"] = "money"

    response = client.post("/data-models", headers=auth_headers, json=payload)

    assert response.status_code == 422


def test_invalid_primary_key_fails(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    payload = type_a_payload()
    payload["primary_key"] = "missing_key"
    payload["attributes"][0]["is_primary_key"] = False

    response = client.post("/data-models", headers=auth_headers, json=payload)

    assert response.status_code == 422


def test_unauthenticated_request_fails(client: TestClient) -> None:
    response = client.get("/data-models")

    assert response.status_code == 401


def test_duplicate_type_a_table_reuses_orphan(
    client: TestClient,
    auth_headers: dict[str, str],
    monkeypatch,
) -> None:
    # data-safety (prompt 34): an existing generated table is an ORPHAN from a previously
    # hard-deleted model — re-creating a same-name model now REUSES it (CREATE TABLE IF NOT EXISTS),
    # never drops it, so the create succeeds instead of erroring.
    monkeypatch.setattr(
        "app.services.table_generator.generated_table_exists",
        lambda db, model_name: True,
    )

    response = client.post("/data-models", headers=auth_headers, json=type_a_payload())

    assert response.status_code == 201, response.text


def test_failed_table_creation_rolls_back_metadata(
    client: TestClient,
    auth_headers: dict[str, str],
    monkeypatch,
) -> None:
    def fail_create(db, model):
        raise RuntimeError("DDL failed")

    monkeypatch.setattr("app.services.table_generator.create_generated_table_for_model", fail_create)

    response = client.post("/data-models", headers=auth_headers, json=type_a_payload())
    list_response = client.get("/data-models", headers=auth_headers)

    assert response.status_code == 500
    assert list_response.json() == []


def test_update_does_not_alter_generated_table(
    client: TestClient,
    auth_headers: dict[str, str],
    monkeypatch,
) -> None:
    calls = {"count": 0}

    def count_create(db, model):
        calls["count"] += 1
        return "mdp_data.dm_invoice"

    monkeypatch.setattr(
        "app.services.table_generator.create_generated_table_for_model",
        count_create,
    )
    create_response = client.post("/data-models", headers=auth_headers, json=type_a_payload())
    data_model_id = create_response.json()["id"]

    update_response = client.put(
        f"/data-models/{data_model_id}",
        headers=auth_headers,
        json={
            "attributes": [
                {
                    "name": "invoice_no",
                    "display_name": "Invoice Number",
                    "data_type": "text",
                    "required": True,
                    "is_primary_key": True,
                },
                {
                    "name": "new_metadata_only_column",
                    "data_type": "text",
                },
            ]
        },
    )

    assert update_response.status_code == 200
    assert update_response.json()["generated_table"] == "mdp_data.dm_invoice"
    assert calls["count"] == 1


def test_create_generated_table_sql_has_system_and_attribute_columns() -> None:
    class Result:
        def scalar(self):
            return True  # pg_timezone_names existence check (prompt 39) → tz is valid

    class Dialect:
        name = "postgresql"

    class Bind:
        dialect = Dialect()

    class FakeSession:
        bind = Bind()

        def __init__(self):
            self.statements = []

        def execute(self, statement, params=None):
            self.statements.append(str(statement))
            return Result()

    class Model:
        name = "invoice"
        attributes = [
            {"name": "invoice_no", "data_type": "text"},
            {"name": "quantity", "data_type": "integer"},
            {"name": "amount", "data_type": "float"},
            {"name": "approved", "data_type": "boolean"},
            {"name": "invoice_date", "data_type": "date"},
            {"name": "posted_at", "data_type": "datetime"},
            {"name": "extra_data", "data_type": "json"},
        ]

    fake_session = FakeSession()

    generated_table = create_generated_table_for_model(fake_session, Model())
    ddl = fake_session.statements[-1]

    assert generated_table == "mdp_data.dm_invoice"
    assert '"id" UUID PRIMARY KEY' in ddl
    assert '"raw_payload" JSONB NULL' in ddl
    # Prompt 39: dm_* timestamps store local (VN) wall-clock — naive TIMESTAMP, tz-shifted default.
    assert '"created_at" TIMESTAMP DEFAULT (now() AT TIME ZONE \'Asia/Ho_Chi_Minh\')' in ddl
    assert '"updated_at" TIMESTAMP DEFAULT (now() AT TIME ZONE \'Asia/Ho_Chi_Minh\')' in ddl
    assert '"invoice_no" TEXT' in ddl
    assert '"quantity" INTEGER' in ddl
    assert '"amount" DOUBLE PRECISION' in ddl
    assert '"approved" BOOLEAN' in ddl
    assert '"invoice_date" DATE' in ddl
    assert '"posted_at" TIMESTAMP' in ddl
    assert '"extra_data" JSONB' in ddl

from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services.procurement_staging_service import EXPECTED_TABLE_COUNTS


def seed_staging(client: TestClient, auth_headers: dict[str, str]) -> None:
    response = client.post("/admin/demo/seed-procurement-staging", headers=auth_headers)
    assert response.status_code == 200


def test_schemas_requires_authentication(client: TestClient) -> None:
    response = client.get("/db-browser/schemas")

    assert response.status_code == 401


def test_schemas_returns_mdp_staging(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    seed_staging(client, auth_headers)

    response = client.get("/db-browser/schemas", headers=auth_headers)

    assert response.status_code == 200
    assert "mdp_staging" in response.json()["schemas"]


def test_tables_endpoint_returns_staging_tables(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    seed_staging(client, auth_headers)

    response = client.get(
        "/db-browser/schemas/mdp_staging/tables",
        headers=auth_headers,
    )

    assert response.status_code == 200
    table_names = {table["table_name"] for table in response.json()["tables"]}
    assert set(EXPECTED_TABLE_COUNTS).issubset(table_names)


def test_columns_endpoint_returns_supplier_code(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    seed_staging(client, auth_headers)

    response = client.get(
        "/db-browser/schemas/mdp_staging/tables/stg_jde_supplier/columns",
        headers=auth_headers,
    )

    assert response.status_code == 200
    columns = response.json()["columns"]
    supplier_code = next(column for column in columns if column["column_name"] == "supplier_code")
    assert supplier_code["ordinal_position"] == 1


def test_preview_endpoint_returns_seeded_supplier_rows(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    seed_staging(client, auth_headers)

    response = client.get(
        "/db-browser/schemas/mdp_staging/tables/stg_jde_supplier/preview",
        headers=auth_headers,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 5
    assert "supplier_code" in body["columns"]
    assert any(row["supplier_code"] == "SUP-1001" for row in body["rows"])


def test_invalid_schema_name_returns_422(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    response = client.get(
        "/db-browser/schemas/mdp_staging;/tables",
        headers=auth_headers,
    )

    assert response.status_code == 422


def test_invalid_table_name_returns_422(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    response = client.get(
        "/db-browser/schemas/mdp_staging/tables/stg_jde_supplier;/columns",
        headers=auth_headers,
    )

    assert response.status_code == 422


def test_system_schemas_are_excluded(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    response = client.get("/db-browser/schemas", headers=auth_headers)

    assert response.status_code == 200
    schemas = response.json()["schemas"]
    assert "pg_catalog" not in schemas
    assert "information_schema" not in schemas
    assert "pg_toast" not in schemas


def test_preview_limit_max_is_enforced(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    seed_staging(client, auth_headers)

    # Cap raised 100 -> 10000 (prompt 34: 50/100/500/1000/All selector) — 500 is honoured now.
    response = client.get(
        "/db-browser/schemas/mdp_staging/tables/stg_jde_supplier/preview?limit=500",
        headers=auth_headers,
    )
    assert response.status_code == 200
    assert response.json()["limit"] == 500

    # The hard ceiling (le=10000) rejects anything above it, so "All" can never SELECT a 58M table.
    capped = client.get(
        "/db-browser/schemas/mdp_staging/tables/stg_jde_supplier/preview?limit=99999",
        headers=auth_headers,
    )
    assert capped.status_code == 422


def test_preview_requires_authentication(client: TestClient) -> None:
    response = client.get(
        "/db-browser/schemas/mdp_staging/tables/stg_jde_supplier/preview",
    )

    assert response.status_code == 401


def test_purchase_order_summary_view_exists(
    client: TestClient,
    auth_headers: dict[str, str],
    db_session: Session,
) -> None:
    seed_staging(client, auth_headers)

    result = db_session.execute(
        text(
            """
            SELECT 1
            FROM sqlite_master
            WHERE type = 'view' AND name = 'vw_jde_purchase_order_summary'
            """
        )
    )

    assert result.first() is not None


def test_db_browser_lists_purchase_order_summary_view(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    seed_staging(client, auth_headers)

    response = client.get(
        "/db-browser/schemas/mdp_staging/tables",
        headers=auth_headers,
    )

    assert response.status_code == 200
    views = {
        table["table_name"]: table["table_type"]
        for table in response.json()["tables"]
    }
    assert views["vw_jde_purchase_order_summary"] == "VIEW"


def test_purchase_order_summary_columns_include_po_and_supplier_name(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    seed_staging(client, auth_headers)

    response = client.get(
        "/db-browser/schemas/mdp_staging/tables/vw_jde_purchase_order_summary/columns",
        headers=auth_headers,
    )

    assert response.status_code == 200
    columns = {column["column_name"] for column in response.json()["columns"]}
    assert {"po_no", "supplier_name"}.issubset(columns)


def test_purchase_order_summary_preview_returns_po_2026_0001(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    seed_staging(client, auth_headers)

    response = client.get(
        "/db-browser/schemas/mdp_staging/tables/vw_jde_purchase_order_summary/preview",
        headers=auth_headers,
    )

    assert response.status_code == 200
    rows = response.json()["rows"]
    first_po = next(row for row in rows if row["po_no"] == "PO-2026-0001")
    assert first_po["supplier_name"] == "ABC Industrial Supplies"
    assert first_po["line_count"] == 2
    assert first_po["payment_status_summary"] == "open"


def test_purchase_order_summary_view_has_one_row_per_po(
    client: TestClient,
    auth_headers: dict[str, str],
    db_session: Session,
) -> None:
    seed_staging(client, auth_headers)

    view_count = db_session.execute(
        text("SELECT COUNT(*) FROM vw_jde_purchase_order_summary")
    ).scalar_one()
    po_count = db_session.execute(
        text("SELECT COUNT(*) FROM stg_jde_po_header")
    ).scalar_one()

    assert view_count == po_count == 5

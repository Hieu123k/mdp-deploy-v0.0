from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.services.procurement_staging_service import (
    EXPECTED_TABLE_COUNTS,
    get_procurement_staging_counts,
    seed_procurement_staging_data,
    staging_schema_exists,
    staging_table_exists,
)


def test_procurement_staging_schema_exists_after_seed(db_session: Session) -> None:
    seed_procurement_staging_data(db_session)

    assert staging_schema_exists(db_session)


def test_all_procurement_staging_tables_exist_after_seed(db_session: Session) -> None:
    seed_procurement_staging_data(db_session)

    for table_name in EXPECTED_TABLE_COUNTS:
        assert staging_table_exists(db_session, table_name)


def test_seed_data_inserts_expected_row_counts(db_session: Session) -> None:
    counts = seed_procurement_staging_data(db_session)

    assert counts == EXPECTED_TABLE_COUNTS


def test_seed_operation_is_idempotent(db_session: Session) -> None:
    first_counts = seed_procurement_staging_data(db_session)
    second_counts = seed_procurement_staging_data(db_session)

    assert first_counts == EXPECTED_TABLE_COUNTS
    assert second_counts == EXPECTED_TABLE_COUNTS
    assert get_procurement_staging_counts(db_session) == EXPECTED_TABLE_COUNTS


def test_summary_endpoint_returns_correct_counts(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    seed_response = client.post(
        "/admin/demo/seed-procurement-staging",
        headers=auth_headers,
    )
    summary_response = client.get(
        "/admin/demo/procurement-staging-summary",
        headers=auth_headers,
    )

    assert seed_response.status_code == 200
    assert summary_response.status_code == 200
    assert summary_response.json()["tables"] == EXPECTED_TABLE_COUNTS


def test_demo_seed_endpoint_requires_jwt(client: TestClient) -> None:
    response = client.post("/admin/demo/seed-procurement-staging")

    assert response.status_code == 401


def test_demo_summary_endpoint_requires_jwt(client: TestClient) -> None:
    response = client.get("/admin/demo/procurement-staging-summary")

    assert response.status_code == 401

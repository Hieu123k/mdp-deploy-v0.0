from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.services.procurement_staging_service import seed_procurement_staging_data


def migration_job_payload(name: str = "jde_supplier_ora2pg") -> dict:
    return {
        "name": name,
        "description": "External ora2pg full load for JDE supplier master",
        "source_system": "JDE Oracle",
        "source_type": "oracle",
        "migration_tool": "ora2pg",
        "source_schema": "PRODDTA",
        "source_table": "F0101",
        "target_schema": "mdp_staging",
        "target_table": "stg_jde_supplier",
        "estimated_rows": 30000000,
        "estimated_size_gb": 30,
        "primary_key_columns": ["supplier_code"],
        "load_mode": "external_bulk",
        "initial_load_strategy": "external_defined",
        "incremental_strategy": "greater_than_last_watermark",
        "watermark_column": "updated_at",
        "watermark_column_type": "datetime",
        "lookback_window_days": 1,
        "validation_level": "basic",
        "config": {"ora2pg_project": "jde_supplier"},
    }


def create_job(client: TestClient, auth_headers: dict[str, str], name: str = "jde_supplier_ora2pg") -> dict:
    response = client.post("/migration-jobs", headers=auth_headers, json=migration_job_payload(name))
    assert response.status_code == 201, response.text
    return response.json()


def test_create_migration_job(client: TestClient, auth_headers: dict[str, str]) -> None:
    created = create_job(client, auth_headers)

    assert created["name"] == "jde_supplier_ora2pg"
    assert created["migration_tool"] == "ora2pg"
    assert created["load_mode"] == "external_bulk"
    assert created["target_schema"] == "mdp_staging"
    assert created["incremental_strategy"] == "greater_than_last_watermark"
    assert created["watermark_column"] == "updated_at"


def test_create_and_update_migration_run(client: TestClient, auth_headers: dict[str, str]) -> None:
    job = create_job(client, auth_headers, "jde_supplier_run_test")

    response = client.post(
        f"/migration-jobs/{job['id']}/runs",
        headers=auth_headers,
        json={
            "run_type": "external_bulk",
            "trigger_type": "external",
            "status": "running",
            "source_row_count": 5,
            "from_watermark": "2026-05-01",
            "to_watermark": "2026-05-31",
            "log_text": "ora2pg started outside MDP",
        },
    )
    assert response.status_code == 201, response.text
    run = response.json()

    update_response = client.put(
        f"/migration-runs/{run['id']}",
        headers=auth_headers,
        json={
            "status": "success",
            "target_row_count": 5,
            "rows_loaded": 5,
            "duration_seconds": 10,
            "to_watermark": "2026-05-31",
            "log_text": "ora2pg finished outside MDP",
        },
    )

    assert update_response.status_code == 200, update_response.text
    assert update_response.json()["status"] == "success"
    assert update_response.json()["rows_loaded"] == 5
    refreshed = client.get(f"/migration-jobs/{job['id']}", headers=auth_headers)
    assert refreshed.status_code == 200
    assert refreshed.json()["last_successful_watermark"] == "2026-05-31"
    assert refreshed.json()["last_successful_run_at"] is not None


def test_validate_target_table_counts_seeded_rows(
    client: TestClient,
    auth_headers: dict[str, str],
    db_session: Session,
) -> None:
    seed_procurement_staging_data(db_session)
    db_session.commit()
    job = create_job(client, auth_headers, "jde_supplier_validate")
    run_response = client.post(
        f"/migration-jobs/{job['id']}/runs",
        headers=auth_headers,
        json={
            "run_type": "external_bulk",
            "trigger_type": "external",
            "status": "success",
            "source_row_count": 5,
            "rows_loaded": 5,
            "duration_seconds": 14400,
            "log_text": "ora2pg pilot: 30GB class table completed in 3-4 hours",
        },
    )
    run = run_response.json()

    response = client.post(f"/migration-runs/{run['id']}/validate-target", headers=auth_headers)

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["status"] == "success"
    assert data["validation_status"] == "pass"
    assert data["source_row_count"] == 5
    assert data["target_row_count"] == 5
    assert data["row_count_match"] is True
    assert len(data["sample_rows"]) > 0
    checks = {validation["check_name"]: validation for validation in data["validations"]}
    assert checks["target_table_exists"]["status"] == "pass"
    assert checks["source_target_row_count"]["status"] == "pass"
    assert checks["source_target_row_count"]["source_value"] == "5"
    assert checks["source_target_row_count"]["target_value"] == "5"
    assert checks["primary_key_null_count:supplier_code"]["target_value"] == "0"
    assert checks["primary_key_duplicate_count"]["target_value"] == "0"
    assert checks["watermark_column:updated_at"]["status"] == "pass"
    assert checks["target_watermark_max"]["target_value"] is not None
    run_detail = client.get(f"/migration-runs/{run['id']}", headers=auth_headers)
    assert run_detail.status_code == 200
    assert run_detail.json()["validation_status"] == "pass"
    assert run_detail.json()["target_max_watermark"] is not None


def test_validate_target_table_warns_on_source_target_row_count_mismatch(
    client: TestClient,
    auth_headers: dict[str, str],
    db_session: Session,
) -> None:
    seed_procurement_staging_data(db_session)
    db_session.commit()
    job = create_job(client, auth_headers, "jde_supplier_count_mismatch")
    run_response = client.post(
        f"/migration-jobs/{job['id']}/runs",
        headers=auth_headers,
        json={
            "run_type": "external_bulk",
            "trigger_type": "external",
            "status": "success",
            "source_row_count": 30_000_000,
            "rows_loaded": 30_000_000,
            "duration_seconds": 14400,
            "log_text": "ora2pg source count copied from pilot log",
        },
    )
    run = run_response.json()

    response = client.post(f"/migration-runs/{run['id']}/validate-target", headers=auth_headers)

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["status"] == "failed"
    assert data["validation_status"] == "fail"
    assert data["row_count_match"] is False
    checks = {validation["check_name"]: validation for validation in data["validations"]}
    assert checks["source_target_row_count"]["status"] == "fail"
    assert checks["source_target_row_count"]["source_value"] == "30000000"
    assert checks["source_target_row_count"]["target_value"] == "5"


def test_validate_target_table_missing_table_fails(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    payload = migration_job_payload("missing_target_job")
    payload["target_table"] = "stg_missing_table"
    job_response = client.post("/migration-jobs", headers=auth_headers, json=payload)
    assert job_response.status_code == 201
    job = job_response.json()
    run_response = client.post(
        f"/migration-jobs/{job['id']}/runs",
        headers=auth_headers,
        json={"run_type": "external_bulk", "trigger_type": "external", "status": "success"},
    )
    run = run_response.json()

    response = client.post(f"/migration-runs/{run['id']}/validate-target", headers=auth_headers)

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "failed"
    assert any(v["check_name"] == "target_table_exists" and v["status"] == "fail" for v in data["validations"])
    run_detail = client.get(f"/migration-runs/{run['id']}", headers=auth_headers)
    assert run_detail.json()["validation_status"] == "fail"


def test_failed_run_does_not_update_last_successful_watermark(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    job = create_job(client, auth_headers, "jde_supplier_failed_watermark")
    success_response = client.post(
        f"/migration-jobs/{job['id']}/runs",
        headers=auth_headers,
        json={"run_type": "external_bulk", "trigger_type": "external", "status": "success", "to_watermark": "2026-05-31"},
    )
    assert success_response.status_code == 201

    failed_response = client.post(
        f"/migration-jobs/{job['id']}/runs",
        headers=auth_headers,
        json={"run_type": "external_bulk", "trigger_type": "external", "status": "failed", "to_watermark": "2026-06-30"},
    )
    assert failed_response.status_code == 201

    refreshed = client.get(f"/migration-jobs/{job['id']}", headers=auth_headers)
    assert refreshed.status_code == 200
    assert refreshed.json()["last_successful_watermark"] == "2026-05-31"
    assert refreshed.json()["last_run_at"] is not None


def test_max_rows_per_run_must_be_positive(client: TestClient, auth_headers: dict[str, str]) -> None:
    payload = migration_job_payload("invalid_max_rows")
    payload["max_rows_per_run"] = 0

    response = client.post("/migration-jobs", headers=auth_headers, json=payload)

    assert response.status_code == 422


def test_list_migration_runs(client: TestClient, auth_headers: dict[str, str]) -> None:
    job = create_job(client, auth_headers, "jde_supplier_list_runs")
    client.post(
        f"/migration-jobs/{job['id']}/runs",
        headers=auth_headers,
        json={"run_type": "external_bulk", "trigger_type": "external", "status": "pending"},
    )

    response = client.get(f"/migration-jobs/{job['id']}/runs", headers=auth_headers)

    assert response.status_code == 200
    assert len(response.json()) == 1


def test_migration_job_requires_auth(client: TestClient) -> None:
    assert client.get("/migration-jobs").status_code == 401
    assert client.post("/migration-jobs", json=migration_job_payload()).status_code == 401

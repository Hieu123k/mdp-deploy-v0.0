from fastapi.testclient import TestClient


def test_jde_workflow_status_requires_auth(client: TestClient) -> None:
    response = client.get("/demo/jde-procurement/workflow-status")

    assert response.status_code == 401


def test_jde_workflow_status_initial_structure(client: TestClient, auth_headers: dict[str, str]) -> None:
    response = client.get("/demo/jde-procurement/workflow-status", headers=auth_headers)

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["status"] == "success"
    assert data["staging"]["procurement_staging_seeded"] is False
    assert data["supplier"]["migration_job_exists"] is False
    assert data["supplier"]["data_model_exists"] is False
    assert data["purchase_order_summary"]["data_model_exists"] is False


def test_jde_workflow_status_updates_after_demo_flow(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    seed_response = client.post("/admin/demo/seed-procurement-staging", headers=auth_headers)
    assert seed_response.status_code == 200

    job_response = client.post(
        "/migration-templates/jde_supplier_master/create-job",
        headers=auth_headers,
        json={},
    )
    assert job_response.status_code == 201, job_response.text
    job = job_response.json()

    run_response = client.post(
        f"/migration-jobs/{job['id']}/runs",
        headers=auth_headers,
        json={
            "run_type": "external_bulk",
            "trigger_type": "external",
            "status": "success",
            "source_row_count": 5,
            "target_row_count": 5,
            "rows_loaded": 5,
            "run_scope": "demo seeded staging data",
        },
    )
    assert run_response.status_code == 201, run_response.text
    run = run_response.json()

    validation_response = client.post(
        f"/migration-runs/{run['id']}/validate-target",
        headers=auth_headers,
    )
    assert validation_response.status_code == 200

    model_response = client.post(
        "/data-model-templates/jde_supplier/create-model",
        headers=auth_headers,
        json={},
    )
    assert model_response.status_code == 201, model_response.text

    status_response = client.get("/demo/jde-procurement/workflow-status", headers=auth_headers)

    assert status_response.status_code == 200
    data = status_response.json()
    assert data["staging"]["procurement_staging_seeded"] is True
    assert data["supplier"]["migration_job_exists"] is True
    assert data["supplier"]["latest_run_status"] == "success"
    assert data["supplier"]["target_validation_status"] == "pass"
    assert data["supplier"]["target_row_count"] == 5
    assert data["supplier"]["data_model_exists"] is True
    assert data["supplier"]["outbound_api_available"] is True

from fastapi.testclient import TestClient


def test_login_success(client: TestClient) -> None:
    response = client.post(
        "/auth/login",
        json={"username": "admin", "password": "admin123"},
    )

    assert response.status_code == 200
    assert response.json()["token_type"] == "bearer"
    assert response.json()["access_token"]


def test_login_failure(client: TestClient) -> None:
    response = client.post(
        "/auth/login",
        json={"username": "admin", "password": "wrong-password"},
    )

    assert response.status_code == 401


def test_auth_me_with_valid_token(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    response = client.get("/auth/me", headers=auth_headers)

    assert response.status_code == 200
    assert response.json()["username"] == "admin"
    assert response.json()["email"] == "admin@mdp.local"


def test_auth_me_without_token_fails(client: TestClient) -> None:
    response = client.get("/auth/me")

    assert response.status_code == 401

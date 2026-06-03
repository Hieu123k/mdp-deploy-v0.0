from fastapi.testclient import TestClient


def test_create_user(client: TestClient, auth_headers: dict[str, str]) -> None:
    response = client.post(
        "/users",
        headers=auth_headers,
        json={
            "username": "planner",
            "email": "planner@mdp.local",
            "password": "planner123",
            "full_name": "Production Planner",
            "role": "admin",
        },
    )

    assert response.status_code == 201
    data = response.json()
    assert data["username"] == "planner"
    assert data["email"] == "planner@mdp.local"
    assert "hashed_password" not in data


def test_list_users(client: TestClient, auth_headers: dict[str, str]) -> None:
    response = client.get("/users", headers=auth_headers)

    assert response.status_code == 200
    users = response.json()
    assert len(users) == 1
    assert users[0]["username"] == "admin"

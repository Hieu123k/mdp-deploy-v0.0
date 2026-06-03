import builtins
from types import SimpleNamespace
from uuid import UUID

from fastapi.testclient import TestClient
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.connection import Connection
from app.services.connection_service import (
    ConnectionTestError,
    build_oracle_dsn,
    encrypt_password,
    test_connection as run_connection_test,
)


def postgresql_payload(name: str = "plant_postgres") -> dict:
    return {
        "name": name,
        "type": "postgresql",
        "description": "Plant PostgreSQL staging database",
        "host": "postgres",
        "port": 5432,
        "database_name": "mdp",
        "username": "mdp_user",
        "password": "mdp_password",
        "config": {"sslmode": "prefer"},
    }


def create_connection(client: TestClient, auth_headers: dict[str, str], payload: dict | None = None) -> dict:
    response = client.post("/connections", headers=auth_headers, json=payload or postgresql_payload())
    assert response.status_code == 201
    return response.json()


def test_create_connection(
    client: TestClient,
    auth_headers: dict[str, str],
    db_session: Session,
) -> None:
    created = create_connection(client, auth_headers)
    stored = db_session.get(Connection, UUID(created["id"]))

    assert created["name"] == "plant_postgres"
    assert created["type"] == "postgresql"
    assert "password" not in created
    assert "encrypted_password" not in created
    assert stored is not None
    assert stored.encrypted_password != "mdp_password"


def test_list_connections(client: TestClient, auth_headers: dict[str, str]) -> None:
    create_connection(client, auth_headers)

    response = client.get("/connections", headers=auth_headers)

    assert response.status_code == 200
    assert response.json()[0]["name"] == "plant_postgres"
    assert "password" not in response.json()[0]
    assert "encrypted_password" not in response.json()[0]


def test_get_connection(client: TestClient, auth_headers: dict[str, str]) -> None:
    created = create_connection(client, auth_headers)

    response = client.get(f"/connections/{created['id']}", headers=auth_headers)

    assert response.status_code == 200
    assert response.json()["id"] == created["id"]


def test_update_connection(client: TestClient, auth_headers: dict[str, str]) -> None:
    created = create_connection(client, auth_headers)

    response = client.put(
        f"/connections/{created['id']}",
        headers=auth_headers,
        json={"description": "Updated connection", "password": "new_password"},
    )

    assert response.status_code == 200
    assert response.json()["description"] == "Updated connection"
    assert "password" not in response.json()
    assert "encrypted_password" not in response.json()


def test_deactivate_connection(client: TestClient, auth_headers: dict[str, str]) -> None:
    created = create_connection(client, auth_headers)

    response = client.delete(f"/connections/{created['id']}", headers=auth_headers)

    assert response.status_code == 200
    assert response.json()["status"] == "inactive"


def test_invalid_connection_type_fails(client: TestClient, auth_headers: dict[str, str]) -> None:
    payload = postgresql_payload()
    payload["type"] = "ftp"

    response = client.post("/connections", headers=auth_headers, json=payload)

    assert response.status_code == 422


def test_rest_api_requires_base_url(client: TestClient, auth_headers: dict[str, str]) -> None:
    response = client.post(
        "/connections",
        headers=auth_headers,
        json={"name": "missing_rest_url", "type": "rest_api"},
    )

    assert response.status_code == 422


def test_postgresql_connection_success_if_local_postgres_available(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    url = make_url(settings.database_url)
    payload = {
        "name": "runtime_postgres",
        "type": "postgresql",
        "host": url.host or "postgres",
        "port": url.port or 5432,
        "database_name": url.database or "mdp",
        "username": url.username or "mdp_user",
        "password": url.password or "mdp_password",
    }
    created = create_connection(client, auth_headers, payload)

    response = client.post(f"/connections/{created['id']}/test", headers=auth_headers)

    assert response.status_code == 200
    assert response.json()["status"] == "success"


def test_invalid_connection_test_fails_gracefully(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    payload = postgresql_payload("bad_postgres")
    payload["host"] = "invalid-host-name"
    created = create_connection(client, auth_headers, payload)

    response = client.post(f"/connections/{created['id']}/test", headers=auth_headers)

    assert response.status_code == 200
    assert response.json()["status"] == "failed"
    assert "PostgreSQL connection failed" in response.json()["message"]


class FakeOracleDb:
    @staticmethod
    def makedsn(host: str, port: int, *, service_name: str | None = None, sid: str | None = None) -> str:
        if service_name:
            return f"{host}:{port}/{service_name}"
        return f"{host}:{port}:{sid}"


def oracle_connection(
    *,
    config: dict | None = None,
    database_name: str | None = "JDEPROD",
    host: str | None = "jde-oracle.local",
    port: int | None = 1521,
    username: str | None = "jde_reader",
    password: str | None = "secret",
) -> Connection:
    return Connection(
        name="jde_oracle",
        type="oracle",
        host=host,
        port=port,
        database_name=database_name,
        username=username,
        encrypted_password=encrypt_password(password),
        config=config or {},
        status="active",
    )


def test_oracle_dsn_building_for_service_name() -> None:
    connection = oracle_connection(
        config={"oracle_connect_mode": "service_name", "service_name": "JDEPRD"}
    )

    dsn = build_oracle_dsn(connection, FakeOracleDb)

    assert dsn == "jde-oracle.local:1521/JDEPRD"


def test_oracle_dsn_building_for_sid() -> None:
    connection = oracle_connection(config={"oracle_connect_mode": "sid", "sid": "JDEPRD"})

    dsn = build_oracle_dsn(connection, FakeOracleDb)

    assert dsn == "jde-oracle.local:1521:JDEPRD"


def test_oracle_dsn_mode_uses_config_dsn_directly() -> None:
    connection = oracle_connection(
        host=None,
        port=None,
        database_name=None,
        config={"oracle_connect_mode": "dsn", "dsn": "dbhost.example.com:1521/JDEPRD"},
    )

    dsn = build_oracle_dsn(connection, FakeOracleDb)

    assert dsn == "dbhost.example.com:1521/JDEPRD"


def test_oracle_missing_driver_is_handled_gracefully(
    monkeypatch,
    db_session: Session,
) -> None:
    original_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "oracledb":
            raise ImportError("missing driver")
        return original_import(name, *args, **kwargs)

    connection = oracle_connection()
    db_session.add(connection)
    db_session.commit()
    db_session.refresh(connection)
    monkeypatch.setattr(builtins, "__import__", fake_import)

    tested = run_connection_test(db_session, connection)

    assert tested.last_test_status == "failed"
    assert "Oracle driver is not available" in tested.last_test_message


def test_oracle_invalid_config_returns_clear_failure() -> None:
    connection = oracle_connection(config={"oracle_connect_mode": "dsn"})

    try:
        build_oracle_dsn(connection, FakeOracleDb)
    except ConnectionTestError as exc:
        assert "dsn is required" in str(exc)
    else:
        raise AssertionError("Expected ConnectionTestError")


def test_oracle_missing_password_returns_clear_failure(db_session: Session) -> None:
    fake_oracledb = SimpleNamespace(makedsn=FakeOracleDb.makedsn)

    def fail_connect(*args, **kwargs):
        raise AssertionError("connect should not be called without password")

    fake_oracledb.connect = fail_connect
    connection = oracle_connection(password=None)
    db_session.add(connection)
    db_session.commit()
    db_session.refresh(connection)

    original_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "oracledb":
            return fake_oracledb
        return original_import(name, *args, **kwargs)

    try:
        builtins.__import__ = fake_import
        tested = run_connection_test(db_session, connection)
    finally:
        builtins.__import__ = original_import

    assert tested.last_test_status == "failed"
    assert "Oracle connection requires password" in tested.last_test_message


def test_unauthenticated_request_fails(client: TestClient) -> None:
    response = client.get("/connections")

    assert response.status_code == 401

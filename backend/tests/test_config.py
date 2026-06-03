import pytest
from pydantic import ValidationError

from app.core.config import Settings


def test_local_environment_allows_demo_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("JWT_SECRET_KEY", raising=False)

    settings = Settings(app_env="local")

    assert settings.app_env == "local"
    assert settings.jwt_secret_key == "change_me"


def test_production_rejects_default_secrets_and_local_cors() -> None:
    with pytest.raises(ValidationError) as exc:
        Settings(
            app_env="production",
            database_url="postgresql+psycopg://mdp_user:mdp_password@postgres:5432/mdp",
            jwt_secret_key="change_me",
            connection_secret_key="change_me_connection_secret_key",
            cors_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
            postgres_password="mdp_password",
        )

    message = str(exc.value)
    assert "JWT_SECRET_KEY must be set to a non-default value" in message
    assert "CONNECTION_SECRET_KEY must be set to a non-default value" in message
    assert "CORS_ORIGINS must include the production frontend origin" in message
    assert "POSTGRES_PASSWORD must be changed from the default value" in message


def test_production_accepts_strong_configuration() -> None:
    settings = Settings(
        app_env="production",
        database_url="postgresql+psycopg://mdp_user:strong_password@postgres:5432/mdp",
        jwt_secret_key="a" * 40,
        connection_secret_key="b" * 40,
        cors_origins=["https://mdp.example.com"],
        postgres_password="strong_password",
    )

    assert settings.app_env == "production"


def test_production_rejects_short_secrets() -> None:
    with pytest.raises(ValidationError) as exc:
        Settings(
            app_env="production",
            database_url="postgresql+psycopg://mdp_user:strong_password@postgres:5432/mdp",
            jwt_secret_key="too_short",
            connection_secret_key="also_short",
            cors_origins=["https://mdp.example.com"],
            postgres_password="strong_password",
        )

    message = str(exc.value)
    assert "JWT_SECRET_KEY must be at least 32 characters" in message
    assert "CONNECTION_SECRET_KEY must be at least 32 characters" in message

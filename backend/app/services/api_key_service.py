import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.api_key import ApiKey
from app.models.transaction import Transaction
from app.schemas.api_key import ApiKeyCreate, ApiKeyUpdate


API_KEY_PREFIX = "mdp_live_"
VISIBLE_PREFIX_LENGTH = 16


@dataclass
class AuthContext:
    auth_type: str
    user_id: uuid.UUID | None = None
    api_key_id: uuid.UUID | None = None
    source_system: str | None = None
    allowed_directions: list[str] | None = None
    allowed_models: list[str] | None = None


class ApiKeyAuthError(Exception):
    pass


class ApiKeyScopeError(Exception):
    pass


def generate_plain_api_key() -> str:
    return f"{API_KEY_PREFIX}{secrets.token_urlsafe(32)}"


def hash_api_key(api_key: str) -> str:
    material = f"{settings.jwt_secret_key}:{api_key}".encode("utf-8")
    return hashlib.sha256(material).hexdigest()


def get_key_prefix(api_key: str) -> str:
    return api_key[:VISIBLE_PREFIX_LENGTH]


def create_api_key(
    db: Session,
    api_key_in: ApiKeyCreate,
    created_by: uuid.UUID | None,
) -> tuple[ApiKey, str]:
    plain_key = generate_plain_api_key()
    api_key = ApiKey(
        name=api_key_in.name,
        description=api_key_in.description,
        key_prefix=get_key_prefix(plain_key),
        hashed_key=hash_api_key(plain_key),
        source_system=api_key_in.source_system,
        allowed_directions=list(api_key_in.allowed_directions),
        allowed_models=api_key_in.allowed_models,
        expires_at=api_key_in.expires_at,
        created_by=created_by,
    )
    db.add(api_key)
    db.commit()
    db.refresh(api_key)
    return api_key, plain_key


def list_api_keys(db: Session) -> list[ApiKey]:
    return list(db.scalars(select(ApiKey).order_by(ApiKey.created_at.desc())))


def get_api_key(db: Session, api_key_id: uuid.UUID) -> ApiKey | None:
    return db.get(ApiKey, api_key_id)


def update_api_key(db: Session, api_key: ApiKey, api_key_in: ApiKeyUpdate) -> ApiKey:
    update_data = api_key_in.model_dump(exclude_unset=True)
    if update_data.get("allowed_models") == []:
        update_data["allowed_models"] = None
    for field, value in update_data.items():
        setattr(api_key, field, list(value) if field == "allowed_directions" else value)
    db.add(api_key)
    db.commit()
    db.refresh(api_key)
    return api_key


def delete_api_key(db: Session, api_key: ApiKey) -> None:
    """Hard-delete an API key so it disappears from the list and can never authenticate again.

    Child ``transactions`` rows are DE-REFERENCED (``api_key_id`` → NULL) first so the FK
    (``fk_transactions_api_key_id``, no ON DELETE → RESTRICT) doesn't block the delete and the audit
    log is PRESERVED — deleting a key removes the credential but never erases its history. (To merely
    pause a key without removing it, use the ``is_active`` toggle / the "Disable" action instead.)
    """
    db.execute(
        update(Transaction).where(Transaction.api_key_id == api_key.id).values(api_key_id=None)
    )
    db.delete(api_key)
    db.commit()


def authenticate_api_key(db: Session, plain_key: str) -> AuthContext:
    hashed_key = hash_api_key(plain_key)
    api_key = db.scalar(select(ApiKey).where(ApiKey.hashed_key == hashed_key))
    if api_key is None or not api_key.is_active:
        raise ApiKeyAuthError("Invalid API key")
    if api_key.expires_at is not None:
        expires_at = api_key.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        if expires_at <= datetime.now(UTC):
            raise ApiKeyAuthError("API key has expired")

    api_key.last_used_at = datetime.now(UTC)
    db.add(api_key)
    db.commit()
    return AuthContext(
        auth_type="api_key",
        api_key_id=api_key.id,
        source_system=api_key.source_system,
        allowed_directions=api_key.allowed_directions,
        allowed_models=api_key.allowed_models,
    )


def enforce_api_key_scope(
    auth_context: AuthContext,
    *,
    direction: str,
    model_name: str,
) -> None:
    if auth_context.auth_type != "api_key":
        return
    if direction not in (auth_context.allowed_directions or []):
        raise ApiKeyScopeError(f"API key is not allowed for {direction}")
    # Allowed-models is now an EXPLICIT allow-list (prompt 40): an empty/NULL scope grants NO model
    # (was previously "blank = all"). A key must be scoped to the models it may use before it works.
    allowed_models = auth_context.allowed_models or []
    if not allowed_models or model_name not in allowed_models:
        raise ApiKeyScopeError(f"API key is not allowed for model {model_name}")

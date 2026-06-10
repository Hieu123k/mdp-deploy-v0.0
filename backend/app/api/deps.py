import uuid
from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.security import decode_access_token
from app.db.session import get_db
from app.models.user import User
from app.services.api_key_service import ApiKeyAuthError, AuthContext, authenticate_api_key
from app.services.user_service import get_user


bearer_scheme = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    db: Annotated[Session, Depends(get_db)],
) -> User:
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authentication credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = credentials.credentials
    subject = decode_access_token(token)
    if subject is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        user_id = uuid.UUID(subject)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    user = get_user(db, user_id)
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Inactive or missing user",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return user


def require_role(*roles: str) -> Callable[..., User]:
    """Dependency factory → 403 unless ``current_user.role`` is in ``roles``.

    RBAC is enforced server-side: the role is resolved from the DB via ``get_current_user``
    (the JWT carries only the subject), so hiding a tab on the front-end is never the only
    guard. Returns the authenticated ``User`` so routes can still read ``current_user``.
    """
    allowed = set(roles)

    def _checker(current_user: Annotated[User, Depends(get_current_user)]) -> User:
        if current_user.role not in allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Requires role: {', '.join(sorted(allowed))}",
            )
        return current_user

    return _checker


require_admin = require_role("admin")


def require_permission(permission_key: str) -> Callable[..., User]:
    """Dependency factory → 403 unless the user's ROLE grants ``permission_key`` in role_permissions.
    ``admin`` is always allowed (implicit-full). This is the capability layer (prompt 34); it composes
    with — does not replace — ``require_role``/``require_admin`` on the core user/role routes."""

    def _checker(
        current_user: Annotated[User, Depends(get_current_user)],
        db: Annotated[Session, Depends(get_db)],
    ) -> User:
        from app.services.permission_service import role_has_permission  # lazy: avoid import cycle

        if not role_has_permission(db, current_user.role, permission_key):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Requires permission: {permission_key}",
            )
        return current_user

    return _checker


def get_request_auth_context(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    db: Annotated[Session, Depends(get_db)],
    x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
) -> AuthContext:
    if credentials is not None:
        subject = decode_access_token(credentials.credentials)
        if subject is not None:
            try:
                user_id = uuid.UUID(subject)
            except ValueError:
                user_id = None
            if user_id is not None:
                user = get_user(db, user_id)
                if user is not None and user.is_active:
                    return AuthContext(auth_type="jwt", user_id=user.id)

    if x_api_key:
        try:
            return authenticate_api_key(db, x_api_key)
        except ApiKeyAuthError as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=str(exc),
                headers={"WWW-Authenticate": "Bearer"},
            ) from exc

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Missing or invalid authentication credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

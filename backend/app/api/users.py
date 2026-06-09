import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.api.deps import require_admin
from app.db.session import get_db
from app.models.user import User
from app.schemas.user import UserCreate, UserRead, UserUpdate
from app.services.user_service import (
    create_user,
    delete_user,
    get_user,
    get_user_by_email,
    get_user_by_username,
    list_users,
    update_user,
)


# User management is admin-only (RBAC BE-enforce): non-admins get 403 on every route here,
# not merely a hidden sidebar item.
router = APIRouter(
    prefix="/users",
    tags=["users"],
    dependencies=[Depends(require_admin)],
)


def ensure_unique_user_fields(
    db: Session,
    username: str | None,
    email: str | None,
    existing_user_id: uuid.UUID | None = None,
) -> None:
    if username:
        existing = get_user_by_username(db, username)
        if existing and existing.id != existing_user_id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Username is already registered",
            )

    if email:
        existing = get_user_by_email(db, email)
        if existing and existing.id != existing_user_id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Email is already registered",
            )


@router.post("", response_model=UserRead, status_code=status.HTTP_201_CREATED)
def create_user_endpoint(
    user_in: UserCreate,
    db: Annotated[Session, Depends(get_db)],
) -> User:
    ensure_unique_user_fields(db, user_in.username, str(user_in.email))
    return create_user(db, user_in)


@router.get("", response_model=list[UserRead])
def list_users_endpoint(db: Annotated[Session, Depends(get_db)]) -> list[User]:
    return list_users(db)


@router.get("/{user_id}", response_model=UserRead)
def get_user_endpoint(
    user_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
) -> User:
    user = get_user(db, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return user


@router.put("/{user_id}", response_model=UserRead)
def update_user_endpoint(
    user_id: uuid.UUID,
    user_in: UserUpdate,
    db: Annotated[Session, Depends(get_db)],
) -> User:
    user = get_user(db, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    ensure_unique_user_fields(
        db,
        user_in.username,
        str(user_in.email) if user_in.email else None,
        existing_user_id=user.id,
    )
    return update_user(db, user, user_in)


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user_endpoint(
    user_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
) -> Response:
    user = get_user(db, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    delete_user(db, user)
    return Response(status_code=status.HTTP_204_NO_CONTENT)

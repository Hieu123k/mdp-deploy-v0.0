from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.security import create_access_token
from app.db.session import get_db
from app.models.user import User
from app.schemas.user import LoginRequest, TokenResponse, UserRead
from app.services.user_service import authenticate_user


router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
def login(
    login_in: LoginRequest,
    db: Annotated[Session, Depends(get_db)],
) -> TokenResponse:
    user = authenticate_user(db, login_in.username, login_in.password)
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
        )

    token = create_access_token(subject=str(user.id))
    return TokenResponse(access_token=token)


@router.get("/me", response_model=UserRead)
def read_me(current_user: Annotated[User, Depends(get_current_user)]) -> User:
    return current_user


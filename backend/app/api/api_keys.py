import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_permission
from app.db.session import get_db
from app.models.api_key import ApiKey
from app.models.user import User
from app.schemas.api_key import ApiKeyCreate, ApiKeyCreateResponse, ApiKeyRead, ApiKeyUpdate
from app.services.api_key_service import (
    create_api_key,
    delete_api_key,
    get_api_key,
    list_api_keys,
    update_api_key,
)


router = APIRouter(
    prefix="/api-keys",
    tags=["api-keys"],
    dependencies=[Depends(get_current_user)],
)


@router.post(
    "",
    response_model=ApiKeyCreateResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("api_key.create"))],
)
def create_api_key_endpoint(
    api_key_in: ApiKeyCreate,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> dict:
    api_key, plain_key = create_api_key(db, api_key_in, current_user.id)
    data = ApiKeyRead.model_validate(api_key).model_dump()
    data["api_key"] = plain_key
    return data


@router.get("", response_model=list[ApiKeyRead])
def list_api_keys_endpoint(db: Annotated[Session, Depends(get_db)]) -> list[ApiKey]:
    return list_api_keys(db)


@router.get("/{api_key_id}", response_model=ApiKeyRead)
def get_api_key_endpoint(
    api_key_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
) -> ApiKey:
    api_key = get_api_key(db, api_key_id)
    if api_key is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="API key not found")
    return api_key


@router.put("/{api_key_id}", response_model=ApiKeyRead)
def update_api_key_endpoint(
    api_key_id: uuid.UUID,
    api_key_in: ApiKeyUpdate,
    db: Annotated[Session, Depends(get_db)],
) -> ApiKey:
    api_key = get_api_key(db, api_key_id)
    if api_key is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="API key not found")
    return update_api_key(db, api_key, api_key_in)


@router.delete(
    "/{api_key_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_permission("api_key.delete"))],
)
def delete_api_key_endpoint(
    api_key_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
) -> None:
    """Hard-delete the key (de-references its transactions to keep the audit log). 204 on success."""
    api_key = get_api_key(db, api_key_id)
    if api_key is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="API key not found")
    delete_api_key(db, api_key)
    return None

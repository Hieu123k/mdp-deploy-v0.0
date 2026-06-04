"""Reference lists API — read for any authenticated user, write for admins only.

Powers the dashboard's editable dropdowns / fixed fields. Writes are restricted to the
managed lists (business reference lists + the ora2pg catalog); behavioural enums are not
exposed here.
"""
from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_admin
from app.db.session import get_db
from app.models.user import User
from app.services import reference_service as svc

router = APIRouter(prefix="/reference", tags=["reference"])


class OptionOut(BaseModel):
    id: uuid.UUID
    list_key: str
    value: str
    label: str | None
    sort_order: int
    extra: dict[str, Any] | None
    is_active: bool


class OptionCreate(BaseModel):
    value: str = Field(min_length=1, max_length=255)
    label: str | None = Field(default=None, max_length=255)
    sort_order: int | None = None
    extra: dict[str, Any] | None = None


class OptionUpdate(BaseModel):
    value: str | None = Field(default=None, min_length=1, max_length=255)
    label: str | None = Field(default=None, max_length=255)
    sort_order: int | None = None
    extra: dict[str, Any] | None = None
    is_active: bool | None = None


def _serialize(o) -> OptionOut:
    return OptionOut(
        id=o.id, list_key=o.list_key, value=o.value, label=o.label,
        sort_order=o.sort_order, extra=o.extra, is_active=o.is_active,
    )


def _check_managed(list_key: str) -> None:
    if list_key not in svc.MANAGED_LIST_KEYS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"List '{list_key}' is not admin-managed",
        )


@router.get("/lists")
def list_keys(
    _: Annotated[User, Depends(get_current_user)],
) -> dict[str, Any]:
    """The managed list keys (so the UI knows which dropdowns are editable)."""
    return {"lists": sorted(svc.MANAGED_LIST_KEYS)}


@router.get("/{list_key}")
def get_list(
    list_key: str,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
    include_inactive: bool = False,
) -> dict[str, Any]:
    options = svc.list_options(db, list_key, include_inactive=include_inactive)
    return {"list_key": list_key, "options": [_serialize(o) for o in options]}


@router.post("/{list_key}", status_code=status.HTTP_201_CREATED)
def create(
    list_key: str,
    payload: OptionCreate,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(require_admin)],
) -> OptionOut:
    _check_managed(list_key)
    active = {o.value for o in svc.list_options(db, list_key, include_inactive=False)}
    if payload.value in active:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Value already exists in this list")
    option = svc.create_option(
        db, list_key, value=payload.value, label=payload.label,
        sort_order=payload.sort_order, extra=payload.extra,
    )
    return _serialize(option)


@router.patch("/{list_key}/{option_id}")
def update(
    list_key: str,
    option_id: uuid.UUID,
    payload: OptionUpdate,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(require_admin)],
) -> OptionOut:
    _check_managed(list_key)
    option = svc.get_option(db, option_id)
    if option is None or option.list_key != list_key:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Option not found")
    updated = svc.update_option(db, option, **payload.model_dump(exclude_unset=True))
    return _serialize(updated)


@router.delete("/{list_key}/{option_id}")
def delete(
    list_key: str,
    option_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
    _: Annotated[User, Depends(require_admin)],
) -> Response:
    _check_managed(list_key)
    option = svc.get_option(db, option_id)
    if option is None or option.list_key != list_key:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Option not found")
    svc.delete_option(db, option)
    return Response(status_code=status.HTTP_204_NO_CONTENT)

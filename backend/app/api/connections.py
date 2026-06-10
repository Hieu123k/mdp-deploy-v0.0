import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_permission
from app.db.session import get_db
from app.models.connection import Connection
from app.models.user import User
from app.schemas.connection import (
    ConnectionCreate,
    ConnectionRead,
    ConnectionTestResponse,
    ConnectionUpdate,
)
from app.services.connection_service import (
    create_connection,
    deactivate_connection,
    get_connection,
    get_connection_by_name,
    list_connections,
    test_connection,
    update_connection,
)


router = APIRouter(
    prefix="/connections",
    tags=["connections"],
    dependencies=[Depends(get_current_user)],
)

ALLOWED_CONNECTION_TYPES = {"postgresql", "oracle", "sqlserver", "rest_api", "mqtt"}


def ensure_unique_name(
    db: Session,
    name: str | None,
    existing_id: uuid.UUID | None = None,
) -> None:
    if not name:
        return
    existing = get_connection_by_name(db, name)
    if existing and existing.id != existing_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Connection name is already registered",
        )


@router.post(
    "",
    response_model=ConnectionRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("connection.manage"))],
)
def create_connection_endpoint(
    connection_in: ConnectionCreate,
    db: Annotated[Session, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> Connection:
    ensure_unique_name(db, connection_in.name)
    return create_connection(db, connection_in, current_user.id)


@router.get("", response_model=list[ConnectionRead])
def list_connections_endpoint(
    db: Annotated[Session, Depends(get_db)],
    type_filter: Annotated[str | None, Query(alias="type")] = None,
    status_filter: Annotated[str | None, Query(alias="status")] = None,
) -> list[Connection]:
    if type_filter is not None and type_filter not in ALLOWED_CONNECTION_TYPES:
        raise HTTPException(status_code=422, detail="Invalid connection type")
    return list_connections(db, connection_type=type_filter, status=status_filter)


@router.get("/{connection_id}", response_model=ConnectionRead)
def get_connection_endpoint(
    connection_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
) -> Connection:
    connection = get_connection(db, connection_id)
    if connection is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Connection not found")
    return connection


@router.put(
    "/{connection_id}",
    response_model=ConnectionRead,
    dependencies=[Depends(require_permission("connection.manage"))],
)
def update_connection_endpoint(
    connection_id: uuid.UUID,
    connection_in: ConnectionUpdate,
    db: Annotated[Session, Depends(get_db)],
) -> Connection:
    connection = get_connection(db, connection_id)
    if connection is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Connection not found")
    ensure_unique_name(db, connection_in.name, existing_id=connection.id)
    try:
        return update_connection(db, connection, connection_in)
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=exc.errors(include_context=False),
        ) from exc


@router.delete(
    "/{connection_id}",
    response_model=ConnectionRead,
    dependencies=[Depends(require_permission("connection.manage"))],
)
def deactivate_connection_endpoint(
    connection_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
) -> Connection:
    connection = get_connection(db, connection_id)
    if connection is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Connection not found")
    return deactivate_connection(db, connection)


@router.post("/{connection_id}/test", response_model=ConnectionTestResponse)
def test_connection_endpoint(
    connection_id: uuid.UUID,
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    connection = get_connection(db, connection_id)
    if connection is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Connection not found")
    tested = test_connection(db, connection)
    return {
        "id": tested.id,
        "status": tested.last_test_status,
        "message": tested.last_test_message,
        "tested_at": tested.last_test_at,
    }

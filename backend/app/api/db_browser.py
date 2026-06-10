from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_permission
from app.db.session import get_db
from app.services.db_browser_service import (
    DbBrowserNotFoundError,
    DbBrowserValidationError,
    list_columns,
    list_schemas,
    list_tables,
    preview_table,
)


router = APIRouter(
    prefix="/db-browser",
    tags=["db-browser"],
    # db_browser.view gates the whole browser (require_permission already implies authentication).
    dependencies=[Depends(require_permission("db_browser.view"))],
)


def translate_browser_error(exc: Exception) -> HTTPException:
    if isinstance(exc, DbBrowserValidationError):
        return HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        )
    if isinstance(exc, DbBrowserNotFoundError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    return HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))


@router.get("/schemas")
def list_schemas_endpoint(db: Annotated[Session, Depends(get_db)]) -> dict:
    return {"schemas": list_schemas(db)}


@router.get("/schemas/{schema_name}/tables")
def list_tables_endpoint(
    schema_name: str,
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    try:
        return {"schema": schema_name, "tables": list_tables(db, schema_name)}
    except (DbBrowserValidationError, DbBrowserNotFoundError) as exc:
        raise translate_browser_error(exc) from exc


@router.get("/schemas/{schema_name}/tables/{table_name}/columns")
def list_columns_endpoint(
    schema_name: str,
    table_name: str,
    db: Annotated[Session, Depends(get_db)],
) -> dict:
    try:
        return {
            "schema": schema_name,
            "table": table_name,
            "columns": list_columns(db, schema_name, table_name),
        }
    except (DbBrowserValidationError, DbBrowserNotFoundError) as exc:
        raise translate_browser_error(exc) from exc


@router.get("/schemas/{schema_name}/tables/{table_name}/preview")
def preview_table_endpoint(
    schema_name: str,
    table_name: str,
    db: Annotated[Session, Depends(get_db)],
    limit: Annotated[int, Query(ge=1, le=10000)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict:
    try:
        return preview_table(
            db,
            schema_name,
            table_name,
            limit=limit,
            offset=offset,
        )
    except (DbBrowserValidationError, DbBrowserNotFoundError) as exc:
        raise translate_browser_error(exc) from exc

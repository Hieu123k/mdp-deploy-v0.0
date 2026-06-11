from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

from app.api.deps import get_request_auth_context
from app.api.envelope import EnvelopeRoute
from app.db.session import get_db
from app.services.api_key_service import ApiKeyScopeError, AuthContext, enforce_api_key_scope
from app.services.outbound_service import (
    OutboundConflictError,
    OutboundQueryError,
    OutboundValidationError,
    get_outbound_by_key,
    list_outbound,
)


# route_class=EnvelopeRoute → every response on this integration router is wrapped {code,message,data}.
router = APIRouter(
    prefix="/outbound",
    tags=["outbound"],
    route_class=EnvelopeRoute,
)


def query_params_to_dict(request: Request) -> dict[str, str]:
    return {key: value for key, value in request.query_params.multi_items()}


@router.get("/{model_name}")
def list_outbound_records(
    model_name: str,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
    include_meta: bool = False,
    include_raw: bool = False,
    auth_context: Annotated[AuthContext, Depends(get_request_auth_context)] = None,
) -> dict[str, Any]:
    try:
        enforce_api_key_scope(auth_context, direction="outbound", model_name=model_name)
        return list_outbound(
            db,
            model_name=model_name,
            query_params=query_params_to_dict(request),
            endpoint=request.url.path,
            limit=limit,
            offset=offset,
            include_meta=include_meta,
            include_raw=include_raw,
            auth_context=auth_context,
        )
    except ApiKeyScopeError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except OutboundValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=exc.errors,
        ) from exc
    except OutboundConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except OutboundQueryError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        ) from exc


@router.get("/{model_name}/{key}")
def get_outbound_record_by_key(
    model_name: str,
    key: str,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    include_meta: bool = False,
    include_raw: bool = False,
    auth_context: Annotated[AuthContext, Depends(get_request_auth_context)] = None,
) -> dict[str, Any]:
    try:
        enforce_api_key_scope(auth_context, direction="outbound", model_name=model_name)
        return get_outbound_by_key(
            db,
            model_name=model_name,
            key=key,
            query_params=query_params_to_dict(request),
            endpoint=request.url.path,
            include_meta=include_meta,
            include_raw=include_raw,
            auth_context=auth_context,
        )
    except ApiKeyScopeError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except LookupError as exc:
        detail = str(exc)
        code = status.HTTP_404_NOT_FOUND if detail == "Record not found" or detail == "Data model not found" else status.HTTP_400_BAD_REQUEST
        raise HTTPException(status_code=code, detail=detail) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except OutboundValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=exc.errors,
        ) from exc
    except OutboundConflictError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except OutboundQueryError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        ) from exc

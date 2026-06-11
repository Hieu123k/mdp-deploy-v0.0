from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_request_auth_context
from app.api.envelope import EnvelopeRoute
from app.db.session import get_db
from app.schemas.transaction import InboundResponse
from app.services.api_key_service import ApiKeyScopeError, AuthContext, enforce_api_key_scope
from app.services.inbound_service import (
    InboundInsertError,
    InboundValidationError,
    receive_inbound_payload,
)


# route_class=EnvelopeRoute → every response on this integration router is wrapped {code,message,data}.
router = APIRouter(
    prefix="/inbound",
    tags=["inbound"],
    route_class=EnvelopeRoute,
)


@router.post("/{model_name}", response_model=InboundResponse)
def receive_inbound_data(
    model_name: str,
    payload: Annotated[Any, Body()],
    db: Annotated[Session, Depends(get_db)],
    auth_context: Annotated[AuthContext, Depends(get_request_auth_context)],
) -> dict[str, Any]:
    endpoint = f"/inbound/{model_name}"
    try:
        enforce_api_key_scope(auth_context, direction="inbound", model_name=model_name)
        return receive_inbound_payload(
            db,
            model_name=model_name,
            payload=payload,
            endpoint=endpoint,
            auth_context=auth_context,
        )
    except ApiKeyScopeError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except InboundValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=exc.errors,
        ) from exc
    except InboundInsertError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        ) from exc

"""Integration-API response envelope (prompt 41) — SCOPED to /inbound + /outbound only.

Every response on the integration routes is wrapped as ``{code, message, data}`` (matching
API_Spec_E2iHUB_to_MDP) while the real HTTP status is preserved. ``code`` is a NUMERIC catalog code
(NOT the HTTP status). The wrapper is applied via ``route_class=EnvelopeRoute`` on the inbound and
outbound routers ONLY — internal/admin/FE endpoints (data-models, migration, streaming, settings,
auth, api-keys management, ora2pg dashboard) keep their raw shape so the frontend never breaks.
"""
from __future__ import annotations

import json
import logging
from enum import IntEnum
from typing import Any

from fastapi import Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger("mdp.envelope")

# The integration surface, in ONE place. The routers carry these prefixes and the app-level
# exception handlers (main.py) re-use this to scope router-originated errors (405, unrouted 404)
# that never reach EnvelopeRoute, while leaving every internal/FE route's raw shape untouched.
INTEGRATION_PREFIXES = ("/inbound", "/outbound")


def is_integration_path(path: str) -> bool:
    """True only for the integration routers' own paths (exact prefix or a sub-path of it)."""
    return any(path == p or path.startswith(p + "/") for p in INTEGRATION_PREFIXES)


class EnvelopeCode(IntEnum):
    """The ONE place the integration response codes live."""
    SUCCESS = 0            # 200
    PARTIAL = 1            # 207
    BAD_REQUEST = 1001     # 400
    UNAUTHORIZED = 1002    # 401
    FORBIDDEN = 1003       # 403
    NOT_FOUND = 1004       # 404
    UNPROCESSABLE = 1005   # 422
    TOO_MANY_REQUESTS = 1006  # 429
    BAD_GATEWAY = 2001     # 502
    GATEWAY_TIMEOUT = 2002  # 504
    INTERNAL = 2003        # 500


_STATUS_TO_CODE: dict[int, EnvelopeCode] = {
    200: EnvelopeCode.SUCCESS,
    207: EnvelopeCode.PARTIAL,
    400: EnvelopeCode.BAD_REQUEST,
    401: EnvelopeCode.UNAUTHORIZED,
    403: EnvelopeCode.FORBIDDEN,
    404: EnvelopeCode.NOT_FOUND,
    422: EnvelopeCode.UNPROCESSABLE,
    429: EnvelopeCode.TOO_MANY_REQUESTS,
    502: EnvelopeCode.BAD_GATEWAY,
    504: EnvelopeCode.GATEWAY_TIMEOUT,
    500: EnvelopeCode.INTERNAL,
}


def code_for_status(status_code: int) -> int:
    """Map an HTTP status to its catalog code. Statuses not explicitly in the catalog (e.g. 409) fall
    back to the generic client-error (4xx) / internal (5xx) code; the precise HTTP status is unchanged."""
    if status_code in _STATUS_TO_CODE:
        return int(_STATUS_TO_CODE[status_code])
    if 200 <= status_code < 300:
        return int(EnvelopeCode.SUCCESS)
    if 400 <= status_code < 500:
        return int(EnvelopeCode.BAD_REQUEST)
    return int(EnvelopeCode.INTERNAL)


def _normalize_error(item: Any) -> dict[str, str]:
    """Normalise a validation error to the spec shape ``{field, msg}`` from either the service shape
    ``{field, message}`` or a FastAPI ``{loc, msg, type}``."""
    if isinstance(item, dict):
        if item.get("field") is not None:
            field = str(item["field"])
        elif "loc" in item:
            field = ".".join(str(p) for p in item["loc"] if p != "body") or "body"
        else:
            field = "error"
        msg = item.get("msg") or item.get("message") or str(item)
        return {"field": field, "msg": str(msg)}
    return {"field": "error", "msg": str(item)}


def _envelope_body(status_code: int, message: str, data: Any) -> dict[str, Any]:
    return {"code": code_for_status(status_code), "message": message, "data": data}


def _json_envelope(status_code: int, message: str, *, errors: list | None = None, data: Any = None) -> JSONResponse:
    body = _envelope_body(status_code, message, {"errors": errors} if errors is not None else data)
    return JSONResponse(content=body, status_code=status_code)


def envelope_from_http_exception(exc: StarletteHTTPException) -> JSONResponse:
    detail = exc.detail
    if exc.status_code == 422 and isinstance(detail, list):
        return _json_envelope(422, "Validation error", errors=[_normalize_error(e) for e in detail])
    message = detail if isinstance(detail, str) else (str(detail) if detail is not None else "Error")
    response = _json_envelope(exc.status_code, message)
    if exc.headers:
        for key, value in exc.headers.items():
            response.headers[key] = value
    return response


def envelope_from_validation_error(exc: RequestValidationError) -> JSONResponse:
    """Envelope a request-validation error → ``{code:1005, message, data:{errors:[{field,msg}]}}``."""
    return _json_envelope(422, "Validation error", errors=[_normalize_error(e) for e in exc.errors()])


def _wrap_success(response: Response) -> Response:
    """Re-wrap a successful JSON response's body as ``{code, message, data:<original>}``, keeping the
    real status code. Non-JSON / body-less responses are returned untouched."""
    body = getattr(response, "body", None)
    if body is None:
        return response
    try:
        data = json.loads(body) if body else None
    except (ValueError, TypeError):
        return response  # not JSON — leave it (shouldn't happen on these routes)
    wrapped = JSONResponse(
        content=_envelope_body(response.status_code, "OK", data),
        status_code=response.status_code,
    )
    for key, value in response.headers.items():
        if key.lower() not in ("content-length", "content-type"):
            wrapped.headers[key] = value
    return wrapped


class EnvelopeRoute(APIRoute):
    """Custom APIRoute that wraps successes AND errors in the ``{code, message, data}`` envelope.
    Applied ONLY to the inbound/outbound routers (``route_class=EnvelopeRoute``), so it intercepts
    those routes' RequestValidationError / HTTPException BEFORE the app-level handlers — internal
    routes are never touched."""

    def get_route_handler(self):
        original_handler = super().get_route_handler()

        async def envelope_handler(request: Request) -> Response:
            try:
                response = await original_handler(request)
            except RequestValidationError as exc:
                return _json_envelope(
                    422, "Validation error", errors=[_normalize_error(e) for e in exc.errors()]
                )
            except StarletteHTTPException as exc:
                return envelope_from_http_exception(exc)
            except Exception as exc:  # pragma: no cover - defensive; never leak a raw 500
                logger.exception("Unhandled error on integration route %s", request.url.path)
                return _json_envelope(500, "Internal server error")
            return _wrap_success(response)

        return envelope_handler

"""Global exception handlers mapping domain errors to HTTP responses."""

from __future__ import annotations

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.core.request_context import get_request_id
from app.domain.errors import GatewayError, http_status_for


async def gateway_error_handler(request: Request, exc: GatewayError) -> JSONResponse:
    status_code = http_status_for(exc.error_code)
    headers: dict[str, str] = {}

    if exc.error_code == "rate_limit_exceeded":
        retry_after_ms = getattr(exc, "retry_after_ms", None)
        if retry_after_ms:
            headers["Retry-After"] = str(max(1, retry_after_ms // 1000))

    body = {
        "error": {
            "message": exc.message,
            "type": exc.error_code,
            "code": exc.error_code,
            "request_id": exc.request_id or get_request_id(),
        }
    }
    return JSONResponse(status_code=status_code, content=body, headers=headers)


async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={
            "error": {
                "message": "Request validation failed",
                "type": "validation_error",
                "code": "validation_error",
                "request_id": get_request_id(),
                "details": exc.errors(),
            }
        },
    )


async def unexpected_error_handler(request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(
        status_code=500,
        content={
            "error": {
                "message": "Internal server error",
                "type": "internal_error",
                "code": "internal_error",
                "request_id": get_request_id(),
            }
        },
    )

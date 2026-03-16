"""Global exception handlers for consistent error responses."""

from dataclasses import dataclass

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.logging import logger
from app.core.metrics import increment


@dataclass
class AppError(Exception):
    """Application-level exception with stable error code mapping."""

    code: str
    message: str
    status_code: int = 400
    details: object | None = None


def _request_id_from(request: Request) -> str:
    request_id = getattr(request.state, "request_id", None)
    return request_id if isinstance(request_id, str) and request_id else "-"


def _build_error(
    *,
    request: Request,
    code: str,
    message: str,
    details: object | None = None,
) -> dict:
    return {
        "error": {
            "code": code,
            "message": message,
            "details": details,
            "request_id": _request_id_from(request),
        }
    }


HTTP_CODE_MAP: dict[int, str] = {
    400: "BAD_REQUEST",
    401: "UNAUTHORIZED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    408: "REQUEST_TIMEOUT",
    409: "CONFLICT",
    422: "VALIDATION_ERROR",
    429: "RATE_LIMITED",
    500: "INTERNAL_ERROR",
    502: "UPSTREAM_UNAVAILABLE",
    503: "UPSTREAM_UNAVAILABLE",
    504: "UPSTREAM_TIMEOUT",
}


async def http_exception_handler(
    request: Request, exc: StarletteHTTPException
) -> JSONResponse:
    """Handle HTTP exceptions with a consistent JSON shape."""
    message = exc.detail if isinstance(exc.detail, str) else "Request failed"
    code = HTTP_CODE_MAP.get(exc.status_code, "HTTP_ERROR")

    return JSONResponse(
        status_code=exc.status_code,
        headers={"X-Request-ID": _request_id_from(request)},
        content=_build_error(
            request=request,
            code=code,
            message=message,
            details=exc.detail,
        ),
    )


async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Handle Pydantic validation errors."""
    increment("error_VALIDATION_ERROR")
    return JSONResponse(
        status_code=422,
        headers={"X-Request-ID": _request_id_from(request)},
        content=_build_error(
            request=request,
            code="VALIDATION_ERROR",
            message="Validation error",
            details=exc.errors(),
        ),
    )


async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    """Handle structured application exceptions."""
    increment(f"error_{exc.code}")
    return JSONResponse(
        status_code=exc.status_code,
        headers={"X-Request-ID": _request_id_from(request)},
        content=_build_error(
            request=request,
            code=exc.code,
            message=exc.message,
            details=exc.details,
        ),
    )


async def unhandled_exception_handler(
    request: Request, exc: Exception
) -> JSONResponse:
    """Catch-all for unhandled exceptions."""
    logger.exception("Unhandled exception on %s %s", request.method, request.url.path)
    increment("error_INTERNAL_ERROR")
    return JSONResponse(
        status_code=500,
        headers={"X-Request-ID": _request_id_from(request)},
        content=_build_error(
            request=request,
            code="INTERNAL_ERROR",
            message="Internal server error",
            details=None,
        ),
    )


def register_exception_handlers(app: FastAPI) -> None:
    """Attach all exception handlers to the FastAPI app."""
    app.add_exception_handler(AppError, app_error_handler)
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)

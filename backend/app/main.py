"""FastAPI application entrypoint."""

from contextlib import asynccontextmanager
from collections.abc import AsyncIterator
from time import perf_counter
from uuid import uuid4

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.sessions import SessionMiddleware

from app.api.router import api_router
from app.core.config import settings
from app.core.exceptions import register_exception_handlers
from app.core.logging import logger, setup_logging
from app.core.request_context import set_request_id


def validate_startup_settings() -> None:
    """Fail fast for insecure or incomplete production settings."""
    if settings.ENVIRONMENT.lower() != "production":
        return

    if settings.SECRET_KEY in {"", "change-me-in-production"} or len(settings.SECRET_KEY) < 32:
        raise RuntimeError(
            "Invalid SECRET_KEY for production. Use a strong random value (>= 32 chars)."
        )

    if not settings.OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY is required in production.")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Startup / shutdown lifecycle hook."""
    setup_logging(level="DEBUG" if settings.DEBUG else "INFO")
    validate_startup_settings()
    logger.info("Starting %s", settings.APP_NAME)
    yield
    logger.info("Shutting down %s", settings.APP_NAME)


def create_app() -> FastAPI:
    """Application factory."""
    app = FastAPI(
        title=settings.APP_NAME,
        lifespan=lifespan,
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
    )

    # ── Session (needed by Authlib for OAuth state) ──
    app.add_middleware(SessionMiddleware, secret_key=settings.SECRET_KEY)

    # ── CORS ─────────────────────────────────────────
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── Exception handlers ───────────────────────────
    register_exception_handlers(app)

    # ── Request ID + request logging middleware ──────
    @app.middleware("http")
    async def request_context_middleware(request, call_next):
        request_id = request.headers.get("X-Request-ID") or str(uuid4())
        request.state.request_id = request_id
        set_request_id(request_id)

        started = perf_counter()
        try:
            response = await call_next(request)
        except RuntimeError:
            # Let configured exception handlers do their work.
            raise
        except Exception as exc:
            elapsed_ms = int((perf_counter() - started) * 1000)
            logger.exception(
                "request_failed method=%s path=%s duration_ms=%d error=%s",
                request.method,
                request.url.path,
                elapsed_ms,
                exc.__class__.__name__,
            )
            response = JSONResponse(
                status_code=500,
                content={
                    "error": {
                        "code": "INTERNAL_ERROR",
                        "message": "Internal server error",
                        "details": None,
                        "request_id": request_id,
                    }
                },
            )

        elapsed_ms = int((perf_counter() - started) * 1000)
        response.headers["X-Request-ID"] = request_id
        logger.info(
            "request_complete method=%s path=%s status=%s duration_ms=%d",
            request.method,
            request.url.path,
            response.status_code,
            elapsed_ms,
        )
        return response

    # ── Routes ───────────────────────────────────────
    app.include_router(api_router, prefix="/api")

    return app


app = create_app()

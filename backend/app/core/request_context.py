"""Request-scoped context helpers (request id propagation)."""

from __future__ import annotations

from contextvars import ContextVar


_request_id_ctx: ContextVar[str] = ContextVar("request_id", default="-")


def set_request_id(request_id: str) -> None:
    """Store the request id in a context variable for logging."""
    _request_id_ctx.set(request_id)


def get_request_id() -> str:
    """Read the current request id from context."""
    return _request_id_ctx.get()

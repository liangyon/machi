"""Structured logging configuration."""

import logging
import sys

from app.core.request_context import get_request_id


class RequestIDFilter(logging.Filter):
    """Inject request_id from context into log records."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = get_request_id()
        return True


def setup_logging(*, level: str = "INFO") -> None:
    """Configure root + app loggers with a consistent format."""
    fmt = "%(asctime)s | %(levelname)-8s | %(name)s | req=%(request_id)s | %(message)s"
    datefmt = "%Y-%m-%d %H:%M:%S"

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(fmt=fmt, datefmt=datefmt))
    handler.addFilter(RequestIDFilter())

    # Root logger
    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()
    root.addHandler(handler)

    # Quieten noisy third-party loggers
    for noisy in ("httpcore", "httpx", "uvicorn.access"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


logger = logging.getLogger("machi")

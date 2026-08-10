"""Structured logging setup (CONVENTIONS.md §6)."""

from __future__ import annotations

import logging
from typing import cast

import structlog
from structlog.stdlib import BoundLogger


def configure_logging() -> None:
    """Configure structlog with JSON output and standard-logger bridging."""
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Return a bound structlog logger for module ``name``."""
    configure_logging()
    return cast(BoundLogger, structlog.get_logger(name))

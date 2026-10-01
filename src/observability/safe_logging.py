"""Logging helpers that keep user prompts and provider payloads out of logs."""

from __future__ import annotations

import logging


def log_exception_safely(logger: logging.Logger, event: str, error: Exception) -> None:
    """Log an operational event without exception text or traceback locals."""
    logger.error("%s (error_type=%s)", event, type(error).__name__)

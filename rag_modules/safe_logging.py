"""Privacy-safe structured failure logging."""

from __future__ import annotations

import logging


def log_failure(
    logger: logging.Logger,
    level: int,
    event: str,
    *,
    code: str,
    error: BaseException,
    request_id: str = "",
) -> None:
    logger.log(
        level,
        "%s code=%s request_id=%s exception_type=%s",
        event,
        str(code),
        str(request_id or "-"),
        type(error).__name__,
    )


__all__ = ["log_failure"]

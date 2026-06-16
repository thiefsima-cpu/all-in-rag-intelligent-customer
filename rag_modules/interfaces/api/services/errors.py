"""Exceptions raised by API service orchestration."""

from __future__ import annotations


class _StreamCancelledError(RuntimeError):
    """Raised when an SSE consumer disconnects and the background runner should stop."""


class SystemNotReadyError(RuntimeError):
    """Raised when the serving runtime exists but artifacts are not answer-ready."""

    def __init__(self, message: str, *, diagnostics: dict):
        super().__init__(message)
        self.diagnostics = diagnostics


class BuildJobNotFoundError(KeyError):
    """Raised when a build job identifier is unknown to the current API service."""

    def __init__(self, job_id: str):
        super().__init__(job_id)
        self.job_id = str(job_id)


class BuildJobConflictError(RuntimeError):
    """Raised when a new build job is submitted while another build job is active."""

    def __init__(self, message: str, *, job: dict):
        super().__init__(message)
        self.job = dict(job)


class ApiBackpressureError(RuntimeError):
    """Raised when answer admission control rejects a request."""

    def __init__(self, message: str = "Serving answer concurrency limit exceeded."):
        super().__init__(message)


__all__ = [
    "ApiBackpressureError",
    "BuildJobConflictError",
    "BuildJobNotFoundError",
    "SystemNotReadyError",
]

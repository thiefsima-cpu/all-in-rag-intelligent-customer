"""Generation client error taxonomy."""

from __future__ import annotations


class GenerationProviderResponseError(RuntimeError):
    """Raised when a model provider returns a structurally invalid response."""

    def __init__(self, message: str, *, failure_code: str) -> None:
        super().__init__(message)
        self.failure_code = str(failure_code)


class GenerationLatencyBudgetExceeded(TimeoutError):
    """Raised when the request-scoped generation deadline is exhausted."""

    failure_code = "generation_latency_budget_exceeded"


def generation_failure_code(error: Exception) -> str:
    explicit_code = str(getattr(error, "failure_code", "") or "")
    if explicit_code:
        return explicit_code
    error_name = error.__class__.__name__.lower()
    error_text = str(error).lower()
    if "timeout" in error_name or "timed out" in error_text or "readtimeout" in error_name:
        return "generation_provider_timeout"
    return "generation_provider_error"


def is_retryable_generation_error(error: Exception) -> bool:
    if isinstance(error, (GenerationProviderResponseError, GenerationLatencyBudgetExceeded)):
        return False
    return generation_failure_code(error) == "generation_provider_timeout"


__all__ = [
    "GenerationLatencyBudgetExceeded",
    "GenerationProviderResponseError",
    "generation_failure_code",
    "is_retryable_generation_error",
]

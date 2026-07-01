"""Generation client error taxonomy."""

from __future__ import annotations

from ...runtime.error_models import generation_error_detail


class GenerationProviderResponseError(RuntimeError):
    """Raised when a model provider returns a structurally invalid response."""

    def __init__(self, message: str, *, failure_code: str) -> None:
        super().__init__(message)
        self.failure_code = str(failure_code)


class GenerationLatencyBudgetExceeded(TimeoutError):
    """Raised when the request-scoped generation deadline is exhausted."""

    failure_code = "generation_latency_budget_exceeded"


def generation_failure_code(error: Exception) -> str:
    return generation_error_detail(error).detail


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

"""Canonical generation client exports."""

from __future__ import annotations

from .adapter import GenerationClientAdapter
from .errors import (
    GenerationLatencyBudgetExceeded,
    GenerationProviderResponseError,
    generation_failure_code,
    is_retryable_generation_error,
)
from .factory import build_openai_client, resolve_api_key

__all__ = [
    "GenerationClientAdapter",
    "GenerationLatencyBudgetExceeded",
    "GenerationProviderResponseError",
    "build_openai_client",
    "generation_failure_code",
    "is_retryable_generation_error",
    "resolve_api_key",
]

"""OpenAI-compatible generation client adapter."""

from __future__ import annotations

import logging
import time
from collections.abc import Generator
from contextvars import ContextVar
from typing import Any, cast

from openai import OpenAI

from ...infra.resilience import CircuitBreaker
from ...runtime_contracts import LLMCompletionResponsePort
from .errors import (
    GenerationLatencyBudgetExceeded,
    GenerationProviderResponseError,
    is_retryable_generation_error,
)
from .parsing import (
    estimate_tokens,
    load_json_payload,
    response_content,
    response_text,
    strip_code_fence,
)
from .usage import GenerationTokenUsageTracker

logger = logging.getLogger(__name__)


class GenerationClientAdapter:
    """Wrap model completion and streaming behavior with retry logic."""

    def __init__(
        self,
        *,
        client: OpenAI,
        model_name: str,
        default_temperature: float,
        request_retries: int,
        stream_timeout_seconds: int,
        circuit_breaker: CircuitBreaker | None = None,
        circuit_breaker_failure_threshold: int = 5,
        circuit_breaker_recovery_seconds: float = 30.0,
    ) -> None:
        self.client = client
        self.model_name = model_name
        self.default_temperature = default_temperature
        self.request_retries = max(1, int(request_retries or 1))
        self.stream_timeout_seconds = max(1, int(stream_timeout_seconds or 45))
        self.circuit_breaker = circuit_breaker or CircuitBreaker(
            failure_threshold=circuit_breaker_failure_threshold,
            recovery_timeout_seconds=circuit_breaker_recovery_seconds,
        )
        self._attempt_count: ContextVar[int] = ContextVar(
            f"generation_attempt_count_{id(self)}",
            default=0,
        )
        self._token_usage = GenerationTokenUsageTracker(f"generation_token_usage_{id(self)}")

    def consume_retry_count(self) -> int:
        attempts = max(0, int(self._attempt_count.get() or 0))
        self._attempt_count.set(0)
        return max(0, attempts - 1)

    def consume_token_usage(self) -> dict[str, int | str]:
        return self._token_usage.consume()

    def create_completion(
        self,
        *,
        prompt: str,
        temperature: float,
        max_tokens: int,
        timeout: int | float,
        model_name: str | None = None,
    ) -> LLMCompletionResponsePort:
        last_exc: Exception | None = None
        request_deadline = time.perf_counter() + max(0.1, float(timeout))
        for attempt in range(self.request_retries):
            self._attempt_count.set(attempt + 1)
            try:
                remaining = request_deadline - time.perf_counter()
                if remaining <= 0:
                    raise GenerationLatencyBudgetExceeded(
                        "Generation request deadline was exhausted."
                    )
                response = self.circuit_breaker.call(
                    self.client.chat.completions.create,
                    model=model_name or self.model_name,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=temperature,
                    max_tokens=max_tokens,
                    timeout=max(0.1, remaining),
                )
                if not self._record_token_usage(response):
                    self._record_estimated_usage(
                        prompt=prompt,
                        completion=response_content(response),
                    )
                return cast(LLMCompletionResponsePort, response)
            except Exception as exc:
                last_exc = exc
                logger.warning("Completion attempt %s failed: %s", attempt + 1, exc)
                if attempt < self.request_retries - 1 and is_retryable_generation_error(exc):
                    remaining = request_deadline - time.perf_counter()
                    if remaining <= 0:
                        break
                    time.sleep(min(attempt + 1, 2, remaining))
                    continue
                break
        if last_exc:
            raise last_exc
        raise RuntimeError("Completion failed without an exception.")

    def stream_prompt(
        self,
        *,
        prompt: str,
        max_tokens: int,
        retries: int,
        temperature: float | None = None,
        timeout_seconds: float | None = None,
    ) -> Generator[str, None, None]:
        last_exc: Exception | None = None
        resolved_temperature = self.default_temperature if temperature is None else temperature
        resolved_attempts = max(1, int(retries or 1))
        resolved_timeout = (
            max(0.1, float(timeout_seconds))
            if timeout_seconds is not None
            else float(self.stream_timeout_seconds)
        )
        request_deadline = time.perf_counter() + resolved_timeout
        for attempt in range(resolved_attempts):
            self._attempt_count.set(attempt + 1)
            emitted_content = False
            circuit_started = False
            try:
                remaining = request_deadline - time.perf_counter()
                if remaining <= 0:
                    raise GenerationLatencyBudgetExceeded(
                        "Streaming generation deadline was exhausted."
                    )
                self.circuit_breaker.before_call()
                circuit_started = True
                response = self.client.chat.completions.create(
                    model=self.model_name,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=resolved_temperature,
                    max_tokens=max_tokens,
                    stream=True,
                    timeout=max(0.1, remaining),
                )
                reported_usage = False
                emitted_chunks: list[str] = []
                for chunk in response:
                    reported_usage = self._record_token_usage(chunk) or reported_usage
                    choices = getattr(chunk, "choices", None) or []
                    if not choices:
                        continue
                    delta = getattr(choices[0], "delta", None)
                    content = getattr(delta, "content", None)
                    if content:
                        emitted_content = True
                        emitted_chunks.append(str(content))
                        yield content
                if not emitted_content:
                    raise GenerationProviderResponseError(
                        "Generation provider returned no stream content.",
                        failure_code="generation_provider_empty_content",
                    )
                if not reported_usage:
                    self._record_estimated_usage(
                        prompt=prompt,
                        completion="".join(emitted_chunks),
                    )
                self.circuit_breaker.record_success()
                return
            except Exception as exc:
                if circuit_started:
                    self.circuit_breaker.record_failure()
                last_exc = exc
                logger.warning(
                    "Streaming generation attempt %s failed: %s",
                    attempt + 1,
                    exc,
                )
                if emitted_content:
                    break
                if attempt < resolved_attempts - 1 and is_retryable_generation_error(exc):
                    remaining = request_deadline - time.perf_counter()
                    if remaining <= 0:
                        break
                    time.sleep(min(attempt + 1, 2, remaining))
                    continue
                break
        if last_exc:
            raise last_exc

    def _record_token_usage(self, response: Any) -> bool:
        return self._token_usage.record_provider(response)

    def _record_estimated_usage(self, *, prompt: str, completion: str) -> None:
        self._token_usage.record_estimated(prompt=prompt, completion=completion)

    _response_content = staticmethod(response_content)
    _estimate_tokens = staticmethod(estimate_tokens)
    response_text = staticmethod(response_text)
    strip_code_fence = staticmethod(strip_code_fence)

    def load_json_payload(self, text: str) -> dict[str, Any]:
        return load_json_payload(text)


__all__ = ["GenerationClientAdapter"]

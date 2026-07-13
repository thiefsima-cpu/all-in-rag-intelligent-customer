"""OpenAI-compatible generation client adapter."""

from __future__ import annotations

import logging
import time
from collections.abc import Generator
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, cast

from openai import OpenAI

from ...contracts import RequestBudgetExceeded, RequestCancelled, RequestControl
from ...infra.resilience import CircuitBreaker
from ...safe_logging import log_failure
from ..ports import LLMCompletionResponsePort
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


@dataclass(frozen=True)
class _StreamingRequest:
    temperature: float
    attempts: int
    deadline: float


@dataclass
class _StreamingAttemptState:
    circuit_started: bool = False
    emitted_content: bool = False
    reported_usage: bool = False
    emitted_chunks: list[str] = field(default_factory=list)


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
        enable_thinking: bool | None = None,
        circuit_breaker: CircuitBreaker | None = None,
        circuit_breaker_failure_threshold: int = 5,
        circuit_breaker_recovery_seconds: float = 30.0,
    ) -> None:
        self.client = client
        self.model_name = model_name
        self.default_temperature = default_temperature
        self.request_retries = max(1, int(request_retries or 1))
        self.stream_timeout_seconds = max(1, int(stream_timeout_seconds or 45))
        self.enable_thinking = enable_thinking
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
        control: RequestControl | None = None,
    ) -> LLMCompletionResponsePort:
        last_exc: Exception | None = None
        configured_deadline = time.perf_counter() + max(0.1, float(timeout))
        request_deadline = (
            min(configured_deadline, control.deadline)
            if control is not None
            else configured_deadline
        )
        for attempt in range(self.request_retries):
            self._attempt_count.set(attempt + 1)
            try:
                if control is not None:
                    control.raise_if_cancelled()
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
                    **self._provider_request_options(),
                )
                if not self._record_token_usage(response):
                    self._record_estimated_usage(
                        prompt=prompt,
                        completion=response_content(response),
                    )
                return cast(LLMCompletionResponsePort, response)
            except (RequestCancelled, RequestBudgetExceeded):
                raise
            except Exception as exc:
                last_exc = exc
                logger.warning("Completion attempt failed: attempt=%s", attempt + 1)
                log_failure(
                    logger,
                    logging.WARNING,
                    "generation_attempt_failed",
                    code="GENERATION_FAILED",
                    error=exc,
                )
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
        control: RequestControl | None = None,
    ) -> Generator[str, None, None]:
        request = self._resolve_stream_request(
            retries=retries, temperature=temperature,
            timeout_seconds=timeout_seconds, control=control,
        )  # fmt: skip
        last_exc: Exception | None = None
        for attempt in range(request.attempts):
            self._attempt_count.set(attempt + 1)
            state = _StreamingAttemptState()
            try:
                yield from self._stream_attempt(
                    prompt=prompt,
                    max_tokens=max_tokens,
                    request=request,
                    state=state,
                    control=control,
                )
                return
            except (RequestCancelled, RequestBudgetExceeded):
                raise
            except Exception as exc:
                last_exc = exc
                if not self._prepare_stream_retry(exc, attempt, request, state):
                    break
        if last_exc:
            raise last_exc

    def _resolve_stream_request(
        self,
        *,
        retries: int,
        temperature: float | None,
        timeout_seconds: float | None,
        control: RequestControl | None,
    ) -> _StreamingRequest:
        resolved_timeout = (
            max(0.1, float(timeout_seconds))
            if timeout_seconds is not None
            else float(self.stream_timeout_seconds)
        )
        configured_deadline = time.perf_counter() + resolved_timeout
        return _StreamingRequest(
            temperature=self.default_temperature if temperature is None else temperature,
            attempts=max(1, int(retries or 1)),
            deadline=(
                min(configured_deadline, control.deadline)
                if control is not None
                else configured_deadline
            ),
        )

    def _stream_attempt(
        self,
        *,
        prompt: str,
        max_tokens: int,
        request: _StreamingRequest,
        state: _StreamingAttemptState,
        control: RequestControl | None,
    ) -> Generator[str, None, None]:
        if control is not None:
            control.raise_if_cancelled()
        remaining = request.deadline - time.perf_counter()
        if remaining <= 0:
            raise GenerationLatencyBudgetExceeded("Streaming generation deadline was exhausted.")
        self.circuit_breaker.before_call()
        state.circuit_started = True
        response = self.client.chat.completions.create(
            model=self.model_name,
            messages=[{"role": "user", "content": prompt}],
            temperature=request.temperature,
            max_tokens=max_tokens,
            stream=True,
            timeout=max(0.1, remaining),
            **self._provider_request_options(),
        )
        yield from self._stream_chunks(response=response, state=state, control=control)
        if not state.emitted_content:
            raise GenerationProviderResponseError(
                "Generation provider returned no stream content.",
                failure_code="generation_provider_empty_content",
            )
        if not state.reported_usage:
            self._record_estimated_usage(prompt=prompt, completion="".join(state.emitted_chunks))
        self.circuit_breaker.record_success()

    def _stream_chunks(
        self,
        *,
        response: Any,
        state: _StreamingAttemptState,
        control: RequestControl | None,
    ) -> Generator[str, None, None]:
        for chunk in response:
            if control is not None:
                control.raise_if_cancelled()
            state.reported_usage = self._record_token_usage(chunk) or state.reported_usage
            choices = getattr(chunk, "choices", None) or []
            if not choices:
                continue
            delta = getattr(choices[0], "delta", None)
            content = getattr(delta, "content", None)
            if content:
                state.emitted_content = True
                state.emitted_chunks.append(str(content))
                yield content

    def _prepare_stream_retry(
        self,
        exc: Exception,
        attempt: int,
        request: _StreamingRequest,
        state: _StreamingAttemptState,
    ) -> bool:
        if state.circuit_started:
            self.circuit_breaker.record_failure()
        logger.warning("Streaming generation attempt failed: attempt=%s", attempt + 1)
        log_failure(
            logger,
            logging.WARNING,
            "generation_attempt_failed",
            code="GENERATION_FAILED",
            error=exc,
        )
        if state.emitted_content or attempt >= request.attempts - 1:
            return False
        if not is_retryable_generation_error(exc):
            return False
        remaining = request.deadline - time.perf_counter()
        if remaining <= 0:
            return False
        time.sleep(min(attempt + 1, 2, remaining))
        return True

    def _record_token_usage(self, response: Any) -> bool:
        return self._token_usage.record_provider(response)

    def _record_estimated_usage(self, *, prompt: str, completion: str) -> None:
        self._token_usage.record_estimated(prompt=prompt, completion=completion)

    def _provider_request_options(self) -> dict[str, Any]:
        if self.enable_thinking is None:
            return {}
        return {"extra_body": {"enable_thinking": bool(self.enable_thinking)}}

    _response_content = staticmethod(response_content)
    _estimate_tokens = staticmethod(estimate_tokens)
    response_text = staticmethod(response_text)
    strip_code_fence = staticmethod(strip_code_fence)

    def load_json_payload(self, text: str) -> dict[str, Any]:
        return load_json_payload(text)


__all__ = ["GenerationClientAdapter"]

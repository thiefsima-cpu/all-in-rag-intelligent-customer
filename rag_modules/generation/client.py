"""OpenAI-compatible generation client helpers."""

from __future__ import annotations

import json
import logging
import math
import os
import re
import time
from contextvars import ContextVar
from typing import Any, Dict, Generator, Optional

from openai import OpenAI

from ..infra.resilience import CircuitBreaker

logger = logging.getLogger(__name__)


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


def resolve_api_key(explicit_key: str = "") -> str:
    resolved_api_key = (
        explicit_key
        or os.getenv("DASHSCOPE_API_KEY")
        or os.getenv("OPENAI_API_KEY")
        or os.getenv("MOONSHOT_API_KEY")
    )
    if not resolved_api_key:
        raise ValueError("Please set DASHSCOPE_API_KEY or OPENAI_API_KEY.")
    return resolved_api_key


def build_openai_client(*, api_key: str, base_url: str) -> OpenAI:
    return OpenAI(api_key=api_key, base_url=base_url, max_retries=0)


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
        self._token_usage: ContextVar[tuple[int, int, int, str]] = ContextVar(
            f"generation_token_usage_{id(self)}",
            default=(0, 0, 0, ""),
        )

    def consume_retry_count(self) -> int:
        attempts = max(0, int(self._attempt_count.get() or 0))
        self._attempt_count.set(0)
        return max(0, attempts - 1)

    def consume_token_usage(self) -> dict[str, int | str]:
        prompt_tokens, completion_tokens, total_tokens, source = self._token_usage.get()
        self._token_usage.set((0, 0, 0, ""))
        return {
            "prompt_tokens": max(0, int(prompt_tokens or 0)),
            "completion_tokens": max(0, int(completion_tokens or 0)),
            "total_tokens": max(0, int(total_tokens or 0)),
            "token_usage_source": str(source or ""),
        }

    def create_completion(
        self,
        *,
        prompt: str,
        temperature: float,
        max_tokens: int,
        timeout: int,
    ):
        last_exc: Optional[Exception] = None
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
                    model=self.model_name,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=temperature,
                    max_tokens=max_tokens,
                    timeout=max(0.1, remaining),
                )
                if not self._record_token_usage(response):
                    self._record_estimated_usage(
                        prompt=prompt,
                        completion=self._response_content(response),
                    )
                return response
            except Exception as exc:
                last_exc = exc
                logger.warning("Completion attempt %s failed: %s", attempt + 1, exc)
                if (
                    attempt < self.request_retries - 1
                    and is_retryable_generation_error(exc)
                ):
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
        temperature: Optional[float] = None,
        timeout_seconds: Optional[float] = None,
    ) -> Generator[str, None, None]:
        last_exc: Optional[Exception] = None
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
                logger.warning("Streaming generation attempt %s failed: %s", attempt + 1, exc)
                if emitted_content:
                    break
                if (
                    attempt < resolved_attempts - 1
                    and is_retryable_generation_error(exc)
                ):
                    remaining = request_deadline - time.perf_counter()
                    if remaining <= 0:
                        break
                    time.sleep(min(attempt + 1, 2, remaining))
                    continue
                break
        if last_exc:
            raise last_exc

    def _record_token_usage(self, response: Any) -> bool:
        usage = (
            response.get("usage")
            if isinstance(response, dict)
            else getattr(response, "usage", None)
        )
        if usage is None:
            return False

        def value(*names: str) -> int:
            for name in names:
                raw = usage.get(name) if isinstance(usage, dict) else getattr(usage, name, None)
                if raw is not None:
                    return max(0, int(raw or 0))
            return 0

        prompt_tokens = value("prompt_tokens", "input_tokens")
        completion_tokens = value("completion_tokens", "output_tokens")
        total_tokens = value("total_tokens") or prompt_tokens + completion_tokens
        current_prompt, current_completion, current_total, _source = (
            self._token_usage.get()
        )
        self._token_usage.set(
            (
                current_prompt + prompt_tokens,
                current_completion + completion_tokens,
                current_total + total_tokens,
                "provider",
            )
        )
        return True

    def _record_estimated_usage(self, *, prompt: str, completion: str) -> None:
        prompt_tokens = self._estimate_tokens(prompt)
        completion_tokens = self._estimate_tokens(completion)
        current_prompt, current_completion, current_total, current_source = (
            self._token_usage.get()
        )
        self._token_usage.set(
            (
                current_prompt + prompt_tokens,
                current_completion + completion_tokens,
                current_total + prompt_tokens + completion_tokens,
                current_source or "estimated",
            )
        )

    @staticmethod
    def _response_content(response: Any) -> str:
        choices = (
            response.get("choices")
            if isinstance(response, dict)
            else getattr(response, "choices", None)
        ) or []
        if not choices:
            return ""
        first = choices[0]
        message = first.get("message") if isinstance(first, dict) else getattr(first, "message", None)
        if message is None:
            return ""
        content = message.get("content") if isinstance(message, dict) else getattr(message, "content", None)
        return str(content or "")

    @staticmethod
    def _estimate_tokens(text: str) -> int:
        value = str(text or "")
        cjk_count = len(re.findall(r"[\u3400-\u9fff]", value))
        non_cjk_count = max(0, len(value) - cjk_count)
        return max(0, cjk_count + math.ceil(non_cjk_count / 4))

    @staticmethod
    def response_text(response) -> str:
        choices = getattr(response, "choices", None) or []
        if not choices:
            raise GenerationProviderResponseError(
                "Generation provider returned no choices.",
                failure_code="generation_provider_empty_choices",
            )
        message = getattr(choices[0], "message", None)
        content = getattr(message, "content", None)
        if not content or not str(content).strip():
            raise GenerationProviderResponseError(
                "Generation provider returned empty content.",
                failure_code="generation_provider_empty_content",
            )
        return str(content).strip()

    @staticmethod
    def strip_code_fence(text: str) -> str:
        stripped = text.strip()
        if stripped.startswith("```"):
            lines = stripped.splitlines()
            if len(lines) >= 2 and lines[-1].strip() == "```":
                return "\n".join(lines[1:-1]).strip()
        return stripped

    def load_json_payload(self, text: str) -> Dict[str, Any]:
        stripped = self.strip_code_fence(text)
        try:
            payload = json.loads(stripped)
            if isinstance(payload, dict):
                return payload
        except json.JSONDecodeError:
            pass

        start = stripped.find("{")
        end = stripped.rfind("}")
        if start >= 0 and end > start:
            payload = json.loads(stripped[start : end + 1])
            if isinstance(payload, dict):
                return payload
        raise ValueError("Planner did not return a valid JSON object.")

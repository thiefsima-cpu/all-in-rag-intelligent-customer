"""Direct generation completion collaborator."""

from __future__ import annotations

import time

from ...contracts import RequestControl
from ...contracts.runtime import AnswerContext
from ..clients import GenerationClientAdapter
from ..models import GenerationSettings
from ..prompt_builder import GenerationPromptBuilder
from .contracts import GenerationAttemptResult
from .timeouts import GenerationExecutionDeadline
from .usage import GenerationUsageCollector


class DirectCompletionRunner:
    def __init__(
        self,
        *,
        settings: GenerationSettings,
        client_adapter: GenerationClientAdapter,
        prompt_builder: GenerationPromptBuilder,
        usage_collector: GenerationUsageCollector,
    ) -> None:
        self._settings = settings
        self._client_adapter = client_adapter
        self._prompt_builder = prompt_builder
        self._usage_collector = usage_collector

    def run(
        self,
        answer_context: AnswerContext,
        *,
        deadline: GenerationExecutionDeadline,
        control: RequestControl | None = None,
    ) -> GenerationAttemptResult:
        if control is not None:
            control.raise_if_cancelled()
        direct_start = time.perf_counter()
        prompt = self._prompt_builder.render_direct_answer_prompt_from_context(answer_context).text
        response = self._client_adapter.create_completion(
            prompt=prompt,
            temperature=self._settings.temperature,
            max_tokens=self._settings.direct_max_tokens,
            timeout=deadline.remaining_timeout(
                self._settings.timeout_seconds,
            ),
            control=control,
        )
        if control is not None:
            control.raise_if_cancelled()
        answer = GenerationClientAdapter.response_text(response)
        return GenerationAttemptResult(
            answer=answer,
            direct_latency_ms=deadline.elapsed_ms_since(direct_start),
            request_retries=self._usage_collector.drain_retry_count(),
        )

    response_text = staticmethod(GenerationClientAdapter.response_text)


__all__ = ["DirectCompletionRunner"]

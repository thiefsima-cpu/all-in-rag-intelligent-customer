"""Direct generation completion helpers."""

from __future__ import annotations

import time

from ...runtime import AnswerContext
from ..client import GenerationClientAdapter


class _DirectCompletionMixin:
    def _run_direct_completion(
        self,
        answer_context: AnswerContext,
        *,
        deadline: float,
    ) -> tuple[str, float, int]:
        direct_start = time.perf_counter()
        prompt = self.prompt_builder.render_direct_answer_prompt_from_context(
            answer_context
        ).text
        response = self.client_adapter.create_completion(
            prompt=prompt,
            temperature=self.settings.temperature,
            max_tokens=self.settings.direct_max_tokens,
            timeout=self._remaining_timeout(
                deadline,
                self.settings.timeout_seconds,
            ),
        )
        answer = self._response_text(response)
        return (
            answer,
            self._elapsed_ms(direct_start),
            self._consume_retry_count() + 1,
        )

    @staticmethod
    def _response_text(response) -> str:
        return GenerationClientAdapter.response_text(response)

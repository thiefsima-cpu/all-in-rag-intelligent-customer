"""Compose-stage generation collaborator."""

from __future__ import annotations

from ...contracts import RequestControl
from ...runtime import AnswerContext
from ..clients import GenerationClientAdapter
from ..models import AnswerPlan, GenerationSettings
from ..prompt_builder import GenerationPromptBuilder


class GenerationComposer:
    def __init__(
        self,
        *,
        settings: GenerationSettings,
        client_adapter: GenerationClientAdapter,
        prompt_builder: GenerationPromptBuilder,
    ) -> None:
        self._settings = settings
        self._client_adapter = client_adapter
        self._prompt_builder = prompt_builder

    def compose_from_context(
        self,
        answer_context: AnswerContext,
        plan: AnswerPlan,
        *,
        timeout_seconds: float | None = None,
        control: RequestControl | None = None,
    ) -> str:
        if control is not None:
            control.raise_if_cancelled()
        prompt = self._prompt_builder.render_compose_prompt_from_context(
            answer_context,
            plan,
        ).text
        response = self._client_adapter.create_completion(
            prompt=prompt,
            temperature=self._settings.temperature,
            max_tokens=self._settings.composer_max_tokens,
            timeout=(
                self._settings.timeout_seconds if timeout_seconds is None else timeout_seconds
            ),
            control=control,
        )
        if control is not None:
            control.raise_if_cancelled()
        return GenerationClientAdapter.response_text(response)


__all__ = ["GenerationComposer"]

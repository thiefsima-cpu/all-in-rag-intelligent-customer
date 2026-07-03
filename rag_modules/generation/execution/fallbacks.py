"""Fallback collaborator for generation execution."""

from __future__ import annotations

from ...answer_evidence_builder import AnswerEvidencePackage
from ..fallback import build_evidence_only_fallback_answer, should_skip_model_fallback
from ..models import GenerationSettings


class GenerationFallbackHandler:
    def __init__(self, *, settings: GenerationSettings) -> None:
        self._settings = settings

    def should_attempt_model_fallback(self, error: Exception) -> bool:
        return not should_skip_model_fallback(
            error,
            fallback_on_timeout=self._settings.fallback_on_timeout,
        )

    @staticmethod
    def build_evidence_only_answer(
        *,
        package: AnswerEvidencePackage,
        error: Exception,
    ) -> str:
        return build_evidence_only_fallback_answer(
            package=package,
            error=error,
            max_items=max(1, len(package.items)),
        )


__all__ = ["GenerationFallbackHandler"]

"""Typing-only host contract shared by generation execution mixins."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ...answer_evidence_builder import AnswerEvidencePackage
from ...runtime import AnalysisInput, AnswerContext, GenerationSnapshot
from ..client import GenerationClientAdapter
from ..models import AnswerPlan, GenerationDecision, GenerationSettings
from ..planner import GenerationPlanner
from ..prompt_builder import GenerationPromptBuilder


class _GenerationExecutionHost:
    client_adapter: GenerationClientAdapter
    empty_evidence_answer: str
    planner: GenerationPlanner
    prompt_builder: GenerationPromptBuilder
    settings: GenerationSettings

    if TYPE_CHECKING:

        def _build_answer_plan(
            self,
            answer_context: AnswerContext,
            *,
            deadline: float,
        ) -> AnswerPlan: ...

        def _build_fallback_answer(
            self,
            *,
            package: AnswerEvidencePackage,
            error: Exception,
            trace: GenerationSnapshot,
            total_start: float,
        ) -> tuple[str, GenerationSnapshot]: ...

        @staticmethod
        def _clone_trace(trace: GenerationSnapshot) -> GenerationSnapshot: ...

        def compose_from_context(
            self,
            answer_context: AnswerContext,
            plan: AnswerPlan,
            *,
            timeout_seconds: float | None = None,
        ) -> str: ...

        def _consume_retry_count(self) -> int: ...

        def _consume_token_usage(self) -> dict[str, Any]: ...

        def _deadline(self, start_time: float) -> float: ...

        @staticmethod
        def _elapsed_ms(start_time: float) -> float: ...

        def _finalize_trace(self, trace: GenerationSnapshot) -> GenerationSnapshot: ...

        def _new_trace(
            self,
            decision: GenerationDecision,
            package: AnswerEvidencePackage,
            selected_package: AnswerEvidencePackage,
        ) -> GenerationSnapshot: ...

        def _record_empty_trace(
            self,
            total_start: float,
            reason: str,
        ) -> tuple[str, GenerationSnapshot]: ...

        @staticmethod
        def _remaining_timeout(deadline: float, configured_timeout: int) -> float: ...

        @staticmethod
        def _response_text(response: object) -> str: ...

        def _resolve_answer_context(
            self,
            *,
            answer_context: AnswerContext | None,
            question: str,
            package: AnswerEvidencePackage | None,
            analysis: AnalysisInput,
        ) -> tuple[AnswerContext, AnswerEvidencePackage]: ...

        def _run_direct_completion(
            self,
            answer_context: AnswerContext,
            *,
            deadline: float,
        ) -> tuple[str, float, int]: ...

        def _snapshot_trace(self, trace: GenerationSnapshot) -> GenerationSnapshot: ...

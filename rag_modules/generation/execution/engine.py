"""Canonical generation execution engine."""

from __future__ import annotations

import logging
import time

from ...answer_evidence_builder import AnswerEvidencePackage
from ...runtime import (
    AnalysisInput,
    AnswerContext,
    GenerationSnapshot,
    RetrievalOutcome,
    ensure_optional_query_analysis,
)
from ...runtime.json_types import coerce_json_object
from ...safe_logging import log_failure
from ..clients import GenerationClientAdapter
from ..decision import decide_generation_mode
from ..models import AnswerPlan, GenerationSettings
from ..planner import GenerationPlanner
from ..prompt_builder import GenerationPromptBuilder
from .direct import _DirectCompletionMixin
from .streaming import _StreamingGenerationMixin
from .timeouts import _GenerationTimeoutMixin
from .tracing import _GenerationTraceMixin
from .two_stage import _TwoStageCompletionMixin

logger = logging.getLogger(__name__)


class GenerationExecutionEngine(
    _StreamingGenerationMixin,
    _TwoStageCompletionMixin,
    _DirectCompletionMixin,
    _GenerationTraceMixin,
    _GenerationTimeoutMixin,
):
    """Own generation execution, retries, fallback, and trace state."""

    def __init__(
        self,
        *,
        settings: GenerationSettings,
        client_adapter: GenerationClientAdapter,
        prompt_builder: GenerationPromptBuilder,
        planner: GenerationPlanner,
        empty_evidence_answer: str,
    ) -> None:
        self.settings = settings
        self.client_adapter = client_adapter
        self.prompt_builder = prompt_builder
        self.planner = planner
        self.empty_evidence_answer = str(empty_evidence_answer or "")

    def generate(
        self,
        *,
        answer_context: AnswerContext | None = None,
        question: str = "",
        package: AnswerEvidencePackage | None = None,
        analysis: AnalysisInput = None,
    ) -> str:
        answer, _trace = self.generate_with_trace(
            answer_context=answer_context,
            question=question,
            package=package,
            analysis=analysis,
        )
        return answer

    def generate_with_trace(
        self,
        *,
        answer_context: AnswerContext | None = None,
        question: str = "",
        package: AnswerEvidencePackage | None = None,
        analysis: AnalysisInput = None,
    ) -> tuple[str, GenerationSnapshot]:
        self._consume_token_usage()
        answer_context, package = self._resolve_answer_context(
            answer_context=answer_context,
            question=question,
            package=package,
            analysis=analysis,
        )
        total_start = time.perf_counter()
        deadline = self._deadline(total_start)
        if not package.items:
            answer, trace = self._record_empty_trace(total_start, "no_evidence")
            return answer, self._finalize_trace(trace)

        decision = decide_generation_mode(
            package=package,
            settings=self.settings,
            analysis=answer_context.analysis,
        )
        selected_package = package.limit_items(decision.evidence_limit)
        selected_context = answer_context.with_evidence_package(selected_package)
        trace = self._new_trace(decision, package, selected_package)

        try:
            if decision.mode == "two_stage":
                answer, trace = self._generate_two_stage_with_fallback(
                    answer_context=selected_context,
                    package=selected_package,
                    trace=trace,
                    total_start=total_start,
                    deadline=deadline,
                )
                return answer, self._finalize_trace(trace)
            answer, direct_latency_ms, attempts_used = self._run_direct_completion(
                selected_context,
                deadline=deadline,
            )
            trace.status = "success"
            trace.direct_latency_ms = direct_latency_ms
            trace.provider_latency_ms = direct_latency_ms
            trace.request_retries = max(0, attempts_used - 1)
            trace.total_latency_ms = self._elapsed_ms(total_start)
            return answer, self._finalize_trace(trace)
        except Exception as exc:
            log_failure(
                logger,
                logging.WARNING,
                "generation_attempt_failed",
                code="GENERATION_FAILED",
                error=exc,
            )
            trace.request_retries += self._consume_retry_count()
            answer, trace = self._build_fallback_answer(
                package=selected_package,
                error=exc,
                trace=trace,
                total_start=total_start,
            )
            return answer, self._finalize_trace(trace)

    def compose(
        self,
        question: str,
        package: AnswerEvidencePackage,
        plan: AnswerPlan,
        *,
        timeout_seconds: float | None = None,
    ) -> str:
        answer_context = AnswerContext(
            question=question,
            retrieval=RetrievalOutcome(query=question),
            evidence_package=coerce_json_object(package.to_dict()),
        )
        return self.compose_from_context(
            answer_context,
            plan,
            timeout_seconds=timeout_seconds,
        )

    def compose_from_context(
        self,
        answer_context: AnswerContext,
        plan: AnswerPlan,
        *,
        timeout_seconds: float | None = None,
    ) -> str:
        prompt = self.prompt_builder.render_compose_prompt_from_context(
            answer_context,
            plan,
        ).text
        response = self.client_adapter.create_completion(
            prompt=prompt,
            temperature=self.settings.temperature,
            max_tokens=self.settings.composer_max_tokens,
            timeout=(self.settings.timeout_seconds if timeout_seconds is None else timeout_seconds),
        )
        return self._response_text(response)

    def _resolve_answer_context(
        self,
        *,
        answer_context: AnswerContext | None,
        question: str,
        package: AnswerEvidencePackage | None,
        analysis: AnalysisInput,
    ) -> tuple[AnswerContext, AnswerEvidencePackage]:
        context = answer_context or AnswerContext(
            question=question,
            retrieval=RetrievalOutcome(query=question),
            analysis=ensure_optional_query_analysis(analysis),
        )
        if package is not None:
            context = context.with_evidence_package(package)
        resolved_package = (
            AnswerEvidencePackage.from_dict(context.evidence_package)
            if context.has_evidence_package
            else AnswerEvidencePackage(question=context.question, items=[])
        )
        return context, resolved_package

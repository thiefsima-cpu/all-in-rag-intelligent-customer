"""Canonical generation execution engine."""

from __future__ import annotations

import logging
from collections.abc import Callable, Generator

from ...contracts import RequestBudgetExceeded, RequestCancelled, RequestControl
from ...contracts.runtime import (
    AnalysisInput,
    AnswerContext,
    GenerationSnapshot,
    RetrievalOutcome,
    ensure_optional_query_analysis,
)
from ...evidence_processing.answer_builder import AnswerEvidencePackage
from ...kernel.json_types import coerce_json_object
from ...safe_logging import log_failure
from ..clients import GenerationClientAdapter
from ..decision import decide_generation_mode
from ..models import AnswerPlan, GenerationDecision, GenerationMode, GenerationSettings
from ..planner import GenerationPlanner
from ..prompt_builder import GenerationPromptBuilder
from .composer import GenerationComposer
from .contracts import GenerationAttemptFailed, GenerationAttemptResult
from .direct import DirectCompletionRunner
from .fallbacks import GenerationFallbackHandler
from .streaming import StreamingGenerationRunner
from .timeouts import GenerationExecutionDeadline, GenerationTimeoutBudget
from .tracing import GenerationTraceRecorder
from .two_stage import TwoStageCompletionRunner
from .usage import GenerationUsageCollector

logger = logging.getLogger(__name__)


class GenerationExecutionEngine:
    """Own generation execution orchestration through explicit collaborators."""

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
        self._timeout_budget = GenerationTimeoutBudget(settings.latency_budget_seconds)
        self._usage_collector = GenerationUsageCollector(client_adapter)
        self._trace_recorder = GenerationTraceRecorder(
            settings_input_cost_per_million_tokens=settings.input_cost_per_million_tokens,
            settings_output_cost_per_million_tokens=settings.output_cost_per_million_tokens,
            prompt_builder=prompt_builder,
            usage_collector=self._usage_collector,
            empty_evidence_answer=self.empty_evidence_answer,
        )
        self._fallback_handler = GenerationFallbackHandler(settings=settings)
        self._composer = GenerationComposer(
            settings=settings,
            client_adapter=client_adapter,
            prompt_builder=prompt_builder,
        )
        self._direct_runner = DirectCompletionRunner(
            settings=settings,
            client_adapter=client_adapter,
            prompt_builder=prompt_builder,
            usage_collector=self._usage_collector,
        )
        self._two_stage_runner = TwoStageCompletionRunner(
            settings=settings,
            planner=planner,
            composer=self._composer,
            direct_runner=self._direct_runner,
            fallback_handler=self._fallback_handler,
            usage_collector=self._usage_collector,
        )
        self._streaming_runner = StreamingGenerationRunner(
            settings=settings,
            client_adapter=client_adapter,
            prompt_builder=prompt_builder,
            timeout_budget=self._timeout_budget,
            usage_collector=self._usage_collector,
            trace_recorder=self._trace_recorder,
            fallback_handler=self._fallback_handler,
            two_stage_runner=self._two_stage_runner,
        )

    def generate(
        self,
        *,
        answer_context: AnswerContext | None = None,
        question: str = "",
        package: AnswerEvidencePackage | None = None,
        analysis: AnalysisInput = None,
        control: RequestControl | None = None,
    ) -> str:
        answer, _trace = self.generate_with_trace(
            answer_context=answer_context,
            question=question,
            package=package,
            analysis=analysis,
            control=control,
        )
        return answer

    def generate_with_trace(
        self,
        *,
        answer_context: AnswerContext | None = None,
        question: str = "",
        package: AnswerEvidencePackage | None = None,
        analysis: AnalysisInput = None,
        control: RequestControl | None = None,
    ) -> tuple[str, GenerationSnapshot]:
        self._usage_collector.reset()
        if control is not None:
            control.raise_if_cancelled()
        answer_context, package = self._resolve_answer_context(
            answer_context=answer_context,
            question=question,
            package=package,
            analysis=analysis,
        )
        deadline = self._timeout_budget.start()
        if control is not None:
            control.raise_if_cancelled()
        if not package.items:
            answer, trace = self._trace_recorder.record_empty_trace(
                total_latency_ms=deadline.total_elapsed_ms(),
                reason="no_evidence",
            )
            return answer, self._trace_recorder.finalize_trace(trace)

        decision = decide_generation_mode(
            package=package,
            settings=self.settings,
            analysis=answer_context.analysis,
        )
        selected_package = package.limit_items(decision.evidence_limit)
        selected_context = answer_context.with_evidence_package(
            coerce_json_object(selected_package.to_dict())
        )
        trace = self._trace_recorder.new_trace(decision, package, selected_package)

        try:
            result = self._run_selected_attempt(
                decision=decision,
                answer_context=selected_context,
                deadline=deadline,
                control=control,
            )
            self._trace_recorder.record_attempt_result(
                trace,
                result,
                total_latency_ms=deadline.total_elapsed_ms(),
            )
            return result.answer, self._trace_recorder.finalize_trace(trace)
        except GenerationAttemptFailed as failure:
            self._trace_recorder.add_retries(trace, failure.request_retries)
            return self._record_generation_fallback(
                trace=trace,
                package=selected_package,
                error=failure.error,
                deadline=deadline,
            )
        except (RequestCancelled, RequestBudgetExceeded):
            raise
        except Exception as exc:
            log_failure(
                logger,
                logging.WARNING,
                "generation_attempt_failed",
                code="GENERATION_FAILED",
                error=exc,
            )
            self._trace_recorder.add_retries(
                trace,
                self._usage_collector.drain_retry_count(),
            )
            return self._record_generation_fallback(
                trace=trace,
                package=selected_package,
                error=exc,
                deadline=deadline,
            )

    def _run_selected_attempt(
        self,
        *,
        decision: GenerationDecision,
        answer_context: AnswerContext,
        deadline: GenerationExecutionDeadline,
        control: RequestControl | None,
    ) -> GenerationAttemptResult:
        if decision.mode is GenerationMode.TWO_STAGE:
            return self._two_stage_runner.run(
                answer_context,
                deadline=deadline,
                control=control,
            )
        return self._direct_runner.run(
            answer_context,
            deadline=deadline,
            control=control,
        )

    def _record_generation_fallback(
        self,
        *,
        trace: GenerationSnapshot,
        package: AnswerEvidencePackage,
        error: Exception,
        deadline: GenerationExecutionDeadline,
    ) -> tuple[str, GenerationSnapshot]:
        answer = self._fallback_handler.build_evidence_only_answer(package=package, error=error)
        self._trace_recorder.record_evidence_fallback(
            trace,
            error=error,
            total_latency_ms=deadline.total_elapsed_ms(),
        )
        return answer, self._trace_recorder.finalize_trace(trace)

    def stream(
        self,
        *,
        answer_context: AnswerContext | None = None,
        question: str = "",
        package: AnswerEvidencePackage | None = None,
        analysis: AnalysisInput = None,
        max_retries: int | None = None,
        control: RequestControl | None = None,
    ) -> Generator[str, None, GenerationSnapshot]:
        answer_context, package = self._resolve_answer_context(
            answer_context=answer_context,
            question=question,
            package=package,
            analysis=analysis,
        )
        return self._streaming_runner.stream(
            answer_context=answer_context,
            package=package,
            max_retries=max_retries,
            control=control,
        )

    def stream_with_trace(
        self,
        *,
        answer_context: AnswerContext | None = None,
        question: str = "",
        package: AnswerEvidencePackage | None = None,
        analysis: AnalysisInput = None,
        max_retries: int | None = None,
        chunk_callback: Callable[[str], None] | None = None,
        control: RequestControl | None = None,
    ) -> tuple[str, GenerationSnapshot]:
        answer_context, package = self._resolve_answer_context(
            answer_context=answer_context,
            question=question,
            package=package,
            analysis=analysis,
        )
        return self._streaming_runner.stream_with_trace(
            answer_context=answer_context,
            package=package,
            max_retries=max_retries,
            chunk_callback=chunk_callback,
            control=control,
        )

    def compose(
        self,
        question: str,
        package: AnswerEvidencePackage,
        plan: AnswerPlan,
        *,
        timeout_seconds: float | None = None,
        control: RequestControl | None = None,
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
            control=control,
        )

    def compose_from_context(
        self,
        answer_context: AnswerContext,
        plan: AnswerPlan,
        *,
        timeout_seconds: float | None = None,
        control: RequestControl | None = None,
    ) -> str:
        return self._composer.compose_from_context(
            answer_context,
            plan,
            timeout_seconds=timeout_seconds,
            control=control,
        )

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
            context = context.with_evidence_package(coerce_json_object(package.to_dict()))
        resolved_package = (
            AnswerEvidencePackage.from_dict(context.evidence_package)
            if context.has_evidence_package
            else AnswerEvidencePackage(question=context.question, items=[])
        )
        return context, resolved_package

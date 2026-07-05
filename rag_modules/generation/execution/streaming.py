"""Streaming generation execution collaborator."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Generator
from dataclasses import dataclass

from ...answer_evidence_builder import AnswerEvidencePackage
from ...contracts import RequestBudgetExceeded, RequestCancelled, RequestControl
from ...contracts.runtime import AnswerContext, GenerationSnapshot
from ...safe_logging import log_failure
from ..clients import GenerationClientAdapter
from ..decision import decide_generation_mode
from ..models import GenerationDecision, GenerationMode, GenerationSettings
from ..prompt_builder import GenerationPromptBuilder
from .contracts import GenerationAttemptResult
from .fallbacks import GenerationFallbackHandler
from .timeouts import GenerationExecutionDeadline, GenerationTimeoutBudget
from .tracing import GenerationTraceRecorder
from .two_stage import TwoStageCompletionRunner
from .usage import GenerationUsageCollector

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _StreamingRequestState:
    decision: GenerationDecision
    selected_package: AnswerEvidencePackage
    selected_context: AnswerContext
    trace: GenerationSnapshot
    deadline: GenerationExecutionDeadline
    resolved_retries: int


class StreamingGenerationRunner:
    def __init__(
        self,
        *,
        settings: GenerationSettings,
        client_adapter: GenerationClientAdapter,
        prompt_builder: GenerationPromptBuilder,
        timeout_budget: GenerationTimeoutBudget,
        usage_collector: GenerationUsageCollector,
        trace_recorder: GenerationTraceRecorder,
        fallback_handler: GenerationFallbackHandler,
        two_stage_runner: TwoStageCompletionRunner,
    ) -> None:
        self._settings = settings
        self._client_adapter = client_adapter
        self._prompt_builder = prompt_builder
        self._timeout_budget = timeout_budget
        self._usage_collector = usage_collector
        self._trace_recorder = trace_recorder
        self._fallback_handler = fallback_handler
        self._two_stage_runner = two_stage_runner

    def stream(
        self,
        *,
        answer_context: AnswerContext,
        package: AnswerEvidencePackage,
        max_retries: int | None = None,
        control: RequestControl | None = None,
    ) -> Generator[str, None, GenerationSnapshot]:
        self._usage_collector.reset()
        deadline = self._start_deadline(control)
        if not package.items:
            answer, trace = self._trace_recorder.record_empty_trace(
                total_latency_ms=deadline.total_elapsed_ms(),
                reason="no_evidence",
            )
            yield answer
            return self._trace_recorder.finalize_trace(trace)

        state = self._prepare_stream_state(
            answer_context=answer_context,
            package=package,
            deadline=deadline,
            max_retries=max_retries,
        )
        trace = state.trace

        try:
            snapshot = yield from self._stream_selected_mode(state, control=control)
            return snapshot
        except (RequestCancelled, RequestBudgetExceeded):
            raise
        except Exception as exc:
            snapshot = yield from self._stream_failure_fallback(state, exc, control=control)
            return snapshot

    def _start_deadline(self, control: RequestControl | None) -> GenerationExecutionDeadline:
        _raise_if_cancelled(control)
        deadline = self._timeout_budget.start()
        _raise_if_cancelled(control)
        return deadline

    def _prepare_stream_state(
        self,
        *,
        answer_context: AnswerContext,
        package: AnswerEvidencePackage,
        deadline: GenerationExecutionDeadline,
        max_retries: int | None,
    ) -> _StreamingRequestState:
        decision = decide_generation_mode(
            package=package,
            settings=self._settings,
            analysis=answer_context.analysis,
        )
        selected_package = package.limit_items(decision.evidence_limit)
        selected_context = answer_context.with_evidence_package(selected_package)
        trace = self._trace_recorder.new_trace(decision, package, selected_package)
        resolved_retries = max(1, int(max_retries or self._settings.stream_retries))
        return _StreamingRequestState(
            decision=decision,
            selected_package=selected_package,
            selected_context=selected_context,
            trace=trace,
            deadline=deadline,
            resolved_retries=resolved_retries,
        )

    def _stream_selected_mode(
        self,
        state: _StreamingRequestState,
        *,
        control: RequestControl | None,
    ) -> Generator[str, None, GenerationSnapshot]:
        if state.decision.mode is GenerationMode.TWO_STAGE:
            return (yield from self._stream_two_stage(state, control=control))
        return (yield from self._stream_direct(state, control=control))

    def _stream_two_stage(
        self,
        state: _StreamingRequestState,
        *,
        control: RequestControl | None,
    ) -> Generator[str, None, GenerationSnapshot]:
        plan, plan_latency_ms, plan_retries = self._two_stage_runner.run_plan_stage(
            state.selected_context,
            deadline=state.deadline,
            control=control,
        )
        self._trace_recorder.record_partial_plan(
            state.trace,
            plan_latency_ms=plan_latency_ms,
            request_retries=plan_retries,
        )
        _raise_if_cancelled(control)
        compose_start = time.perf_counter()
        prompt = self._prompt_builder.render_compose_prompt_from_context(
            state.selected_context,
            plan,
        ).text
        yield from self._stream_prompt(
            state,
            prompt=prompt,
            max_tokens=self._settings.composer_max_tokens,
            control=control,
        )
        self._trace_recorder.record_attempt_result(
            state.trace,
            GenerationAttemptResult(
                answer="",
                plan_latency_ms=plan_latency_ms,
                compose_latency_ms=state.deadline.elapsed_ms_since(compose_start),
                request_retries=self._usage_collector.drain_retry_count(),
            ),
            total_latency_ms=state.deadline.total_elapsed_ms(),
        )
        return self._trace_recorder.finalize_trace(state.trace)

    def _stream_direct(
        self,
        state: _StreamingRequestState,
        *,
        control: RequestControl | None,
    ) -> Generator[str, None, GenerationSnapshot]:
        prompt = self._prompt_builder.render_direct_answer_prompt_from_context(
            state.selected_context
        ).text
        direct_start = time.perf_counter()
        yield from self._stream_prompt(
            state,
            prompt=prompt,
            max_tokens=self._settings.direct_max_tokens,
            control=control,
        )
        self._trace_recorder.record_attempt_result(
            state.trace,
            GenerationAttemptResult(
                answer="",
                direct_latency_ms=state.deadline.elapsed_ms_since(direct_start),
                request_retries=self._usage_collector.drain_retry_count(),
            ),
            total_latency_ms=state.deadline.total_elapsed_ms(),
        )
        return self._trace_recorder.finalize_trace(state.trace)

    def _stream_prompt(
        self,
        state: _StreamingRequestState,
        *,
        prompt: str,
        max_tokens: int,
        control: RequestControl | None,
    ) -> Generator[str, None, None]:
        for chunk in self._client_adapter.stream_prompt(
            prompt=prompt,
            max_tokens=max_tokens,
            retries=state.resolved_retries,
            temperature=self._settings.temperature,
            timeout_seconds=state.deadline.remaining_timeout(
                self._settings.stream_timeout_seconds,
            ),
            control=control,
        ):
            _raise_if_cancelled(control)
            yield chunk

    def _stream_failure_fallback(
        self,
        state: _StreamingRequestState,
        exc: Exception,
        *,
        control: RequestControl | None,
    ) -> Generator[str, None, GenerationSnapshot]:
        log_failure(
            logger,
            logging.WARNING,
            "generation_attempt_failed",
            code="GENERATION_FAILED",
            error=exc,
        )
        self._trace_recorder.add_retries(
            state.trace,
            self._usage_collector.drain_retry_count(),
        )
        if self._should_attempt_stream_fallback(state, exc):
            try:
                return (yield from self._stream_direct_fallback(state, exc, control=control))
            except (RequestCancelled, RequestBudgetExceeded):
                raise
            except Exception as fallback_exc:
                log_failure(
                    logger,
                    logging.WARNING,
                    "generation_fallback_failed",
                    code="GENERATION_FAILED",
                    error=fallback_exc,
                )
                self._trace_recorder.add_retries(
                    state.trace,
                    self._usage_collector.drain_retry_count(),
                )
                exc = fallback_exc

        answer = self._fallback_handler.build_evidence_only_answer(
            package=state.selected_package,
            error=exc,
        )
        self._trace_recorder.record_evidence_fallback(
            state.trace,
            error=exc,
            total_latency_ms=state.deadline.total_elapsed_ms(),
        )
        yield answer
        return self._trace_recorder.finalize_trace(state.trace)

    def _should_attempt_stream_fallback(
        self,
        state: _StreamingRequestState,
        exc: Exception,
    ) -> bool:
        return (
            state.decision.mode is GenerationMode.TWO_STAGE
            and self._fallback_handler.should_attempt_model_fallback(exc)
        )

    def _stream_direct_fallback(
        self,
        state: _StreamingRequestState,
        original_exc: Exception,
        *,
        control: RequestControl | None,
    ) -> Generator[str, None, GenerationSnapshot]:
        prompt = self._prompt_builder.render_direct_answer_prompt_from_context(
            state.selected_context
        ).text
        direct_start = time.perf_counter()
        yield from self._stream_prompt(
            state,
            prompt=prompt,
            max_tokens=self._settings.direct_max_tokens,
            control=control,
        )
        self._trace_recorder.record_attempt_result(
            state.trace,
            GenerationAttemptResult(
                answer="",
                plan_latency_ms=state.trace.plan_latency_ms,
                compose_latency_ms=state.trace.compose_latency_ms,
                direct_latency_ms=state.deadline.elapsed_ms_since(direct_start),
                request_retries=self._usage_collector.drain_retry_count(),
                status="degraded",
                fallback_used=True,
                fallback_reason="two_stage_to_direct_stream",
                failure=original_exc,
            ),
            total_latency_ms=state.deadline.total_elapsed_ms(),
        )
        return self._trace_recorder.finalize_trace(state.trace)

    def stream_with_trace(
        self,
        *,
        answer_context: AnswerContext,
        package: AnswerEvidencePackage,
        max_retries: int | None = None,
        chunk_callback: Callable[[str], None] | None = None,
        control: RequestControl | None = None,
    ) -> tuple[str, GenerationSnapshot]:
        chunks: list[str] = []
        generator = self.stream(
            answer_context=answer_context,
            package=package,
            max_retries=max_retries,
            control=control,
        )
        while True:
            try:
                if control is not None:
                    control.raise_if_cancelled()
                chunk = next(generator)
            except StopIteration as stop:
                trace = stop.value or GenerationSnapshot()
                answer = "".join(chunks).strip() or "Streaming output completed"
                return answer, self._trace_recorder.clone_trace(trace)
            if control is not None:
                control.raise_if_cancelled()
            chunks.append(chunk)
            if chunk_callback:
                chunk_callback(chunk)


def _raise_if_cancelled(control: RequestControl | None) -> None:
    if control is not None:
        control.raise_if_cancelled()


__all__ = ["StreamingGenerationRunner"]

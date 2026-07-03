"""Streaming generation execution collaborator."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Generator

from ...answer_evidence_builder import AnswerEvidencePackage
from ...contracts import RequestBudgetExceeded, RequestCancelled, RequestControl
from ...runtime import AnswerContext, GenerationSnapshot
from ...safe_logging import log_failure
from ..clients import GenerationClientAdapter
from ..decision import decide_generation_mode
from ..models import GenerationMode, GenerationSettings
from ..prompt_builder import GenerationPromptBuilder
from .contracts import GenerationAttemptResult
from .fallbacks import GenerationFallbackHandler
from .timeouts import GenerationTimeoutBudget
from .tracing import GenerationTraceRecorder
from .two_stage import TwoStageCompletionRunner
from .usage import GenerationUsageCollector

logger = logging.getLogger(__name__)


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
        if control is not None:
            control.raise_if_cancelled()
        deadline = self._timeout_budget.start()
        if control is not None:
            control.raise_if_cancelled()
        if not package.items:
            answer, trace = self._trace_recorder.record_empty_trace(
                total_latency_ms=deadline.total_elapsed_ms(),
                reason="no_evidence",
            )
            yield answer
            return self._trace_recorder.finalize_trace(trace)

        decision = decide_generation_mode(
            package=package,
            settings=self._settings,
            analysis=answer_context.analysis,
        )
        selected_package = package.limit_items(decision.evidence_limit)
        selected_context = answer_context.with_evidence_package(selected_package)
        trace = self._trace_recorder.new_trace(decision, package, selected_package)
        resolved_retries = max(1, int(max_retries or self._settings.stream_retries))

        try:
            if decision.mode is GenerationMode.TWO_STAGE:
                plan, plan_latency_ms, plan_retries = self._two_stage_runner.run_plan_stage(
                    selected_context,
                    deadline=deadline,
                    control=control,
                )
                self._trace_recorder.record_partial_plan(
                    trace,
                    plan_latency_ms=plan_latency_ms,
                    request_retries=plan_retries,
                )
                if control is not None:
                    control.raise_if_cancelled()
                compose_start = time.perf_counter()
                prompt = self._prompt_builder.render_compose_prompt_from_context(
                    selected_context,
                    plan,
                ).text
                for chunk in self._client_adapter.stream_prompt(
                    prompt=prompt,
                    max_tokens=self._settings.composer_max_tokens,
                    retries=resolved_retries,
                    temperature=self._settings.temperature,
                    timeout_seconds=deadline.remaining_timeout(
                        self._settings.stream_timeout_seconds,
                    ),
                    control=control,
                ):
                    if control is not None:
                        control.raise_if_cancelled()
                    yield chunk
                self._trace_recorder.record_attempt_result(
                    trace,
                    GenerationAttemptResult(
                        answer="",
                        plan_latency_ms=plan_latency_ms,
                        compose_latency_ms=deadline.elapsed_ms_since(compose_start),
                        request_retries=self._usage_collector.drain_retry_count(),
                    ),
                    total_latency_ms=deadline.total_elapsed_ms(),
                )
                return self._trace_recorder.finalize_trace(trace)

            prompt = self._prompt_builder.render_direct_answer_prompt_from_context(
                selected_context
            ).text
            direct_start = time.perf_counter()
            for chunk in self._client_adapter.stream_prompt(
                prompt=prompt,
                max_tokens=self._settings.direct_max_tokens,
                retries=resolved_retries,
                temperature=self._settings.temperature,
                timeout_seconds=deadline.remaining_timeout(
                    self._settings.stream_timeout_seconds,
                ),
                control=control,
            ):
                if control is not None:
                    control.raise_if_cancelled()
                yield chunk
            self._trace_recorder.record_attempt_result(
                trace,
                GenerationAttemptResult(
                    answer="",
                    direct_latency_ms=deadline.elapsed_ms_since(direct_start),
                    request_retries=self._usage_collector.drain_retry_count(),
                ),
                total_latency_ms=deadline.total_elapsed_ms(),
            )
            return self._trace_recorder.finalize_trace(trace)
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
            if (
                decision.mode is GenerationMode.TWO_STAGE
                and self._fallback_handler.should_attempt_model_fallback(exc)
            ):
                try:
                    prompt = self._prompt_builder.render_direct_answer_prompt_from_context(
                        selected_context
                    ).text
                    direct_start = time.perf_counter()
                    for chunk in self._client_adapter.stream_prompt(
                        prompt=prompt,
                        max_tokens=self._settings.direct_max_tokens,
                        retries=resolved_retries,
                        temperature=self._settings.temperature,
                        timeout_seconds=deadline.remaining_timeout(
                            self._settings.stream_timeout_seconds,
                        ),
                        control=control,
                    ):
                        if control is not None:
                            control.raise_if_cancelled()
                        yield chunk
                    self._trace_recorder.record_attempt_result(
                        trace,
                        GenerationAttemptResult(
                            answer="",
                            plan_latency_ms=trace.plan_latency_ms,
                            compose_latency_ms=trace.compose_latency_ms,
                            direct_latency_ms=deadline.elapsed_ms_since(direct_start),
                            request_retries=self._usage_collector.drain_retry_count(),
                            status="degraded",
                            fallback_used=True,
                            fallback_reason="two_stage_to_direct_stream",
                            failure=exc,
                        ),
                        total_latency_ms=deadline.total_elapsed_ms(),
                    )
                    return self._trace_recorder.finalize_trace(trace)
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
                        trace,
                        self._usage_collector.drain_retry_count(),
                    )
                    exc = fallback_exc

            answer = self._fallback_handler.build_evidence_only_answer(
                package=selected_package,
                error=exc,
            )
            self._trace_recorder.record_evidence_fallback(
                trace,
                error=exc,
                total_latency_ms=deadline.total_elapsed_ms(),
            )
            yield answer
            return self._trace_recorder.finalize_trace(trace)

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


__all__ = ["StreamingGenerationRunner"]

"""Streaming generation execution helpers."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Generator

from ...answer_evidence_builder import AnswerEvidencePackage
from ...runtime import AnalysisInput, AnswerContext, GenerationSnapshot
from ...safe_logging import log_failure
from ..clients import generation_failure_code
from ..decision import decide_generation_mode
from ..fallback import should_skip_model_fallback
from ..models import GenerationMode
from .contracts import _GenerationExecutionHost

logger = logging.getLogger(__name__)


class _StreamingGenerationMixin(_GenerationExecutionHost):
    def stream(
        self,
        *,
        answer_context: AnswerContext | None = None,
        question: str = "",
        package: AnswerEvidencePackage | None = None,
        analysis: AnalysisInput = None,
        max_retries: int | None = None,
    ) -> Generator[str, None, GenerationSnapshot]:
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
            yield answer
            return self._finalize_trace(trace)

        decision = decide_generation_mode(
            package=package,
            settings=self.settings,
            analysis=answer_context.analysis,
        )
        selected_package = package.limit_items(decision.evidence_limit)
        selected_context = answer_context.with_evidence_package(selected_package)
        trace = self._new_trace(decision, package, selected_package)
        resolved_retries = max(1, int(max_retries or self.settings.stream_retries))

        try:
            if decision.mode is GenerationMode.TWO_STAGE:
                plan_start = time.perf_counter()
                plan = self._build_answer_plan(
                    selected_context,
                    deadline=deadline,
                )
                trace.plan_latency_ms = self._elapsed_ms(plan_start)
                compose_start = time.perf_counter()
                prompt = self.prompt_builder.render_compose_prompt_from_context(
                    selected_context,
                    plan,
                ).text
                for chunk in self.client_adapter.stream_prompt(
                    prompt=prompt,
                    max_tokens=self.settings.composer_max_tokens,
                    retries=resolved_retries,
                    temperature=self.settings.temperature,
                    timeout_seconds=self._remaining_timeout(
                        deadline,
                        self.settings.stream_timeout_seconds,
                    ),
                ):
                    yield chunk
                trace.status = "success"
                trace.compose_latency_ms = self._elapsed_ms(compose_start)
                trace.provider_latency_ms = trace.plan_latency_ms + trace.compose_latency_ms
                trace.request_retries += self._consume_retry_count()
                trace.total_latency_ms = self._elapsed_ms(total_start)
                return self._finalize_trace(trace)

            prompt = self.prompt_builder.render_direct_answer_prompt_from_context(
                selected_context
            ).text
            direct_start = time.perf_counter()
            for chunk in self.client_adapter.stream_prompt(
                prompt=prompt,
                max_tokens=self.settings.direct_max_tokens,
                retries=resolved_retries,
                temperature=self.settings.temperature,
                timeout_seconds=self._remaining_timeout(
                    deadline,
                    self.settings.stream_timeout_seconds,
                ),
            ):
                yield chunk
            trace.status = "success"
            trace.direct_latency_ms = self._elapsed_ms(direct_start)
            trace.provider_latency_ms = trace.direct_latency_ms
            trace.request_retries += self._consume_retry_count()
            trace.total_latency_ms = self._elapsed_ms(total_start)
            return self._finalize_trace(trace)
        except Exception as exc:
            log_failure(
                logger,
                logging.WARNING,
                "generation_attempt_failed",
                code="GENERATION_FAILED",
                error=exc,
            )
            trace.request_retries += self._consume_retry_count()
            if decision.mode is GenerationMode.TWO_STAGE and not should_skip_model_fallback(
                exc,
                fallback_on_timeout=self.settings.fallback_on_timeout,
            ):
                try:
                    trace.fallback_used = True
                    trace.fallback_reason = "two_stage_to_direct_stream"
                    prompt = self.prompt_builder.render_direct_answer_prompt_from_context(
                        selected_context
                    ).text
                    direct_start = time.perf_counter()
                    for chunk in self.client_adapter.stream_prompt(
                        prompt=prompt,
                        max_tokens=self.settings.direct_max_tokens,
                        retries=resolved_retries,
                        temperature=self.settings.temperature,
                        timeout_seconds=self._remaining_timeout(
                            deadline,
                            self.settings.stream_timeout_seconds,
                        ),
                    ):
                        yield chunk
                    trace.status = "degraded"
                    trace.direct_latency_ms = self._elapsed_ms(direct_start)
                    trace.provider_latency_ms = (
                        trace.plan_latency_ms + trace.compose_latency_ms + trace.direct_latency_ms
                    )
                    trace.failure_code = generation_failure_code(exc)
                    trace.request_retries += self._consume_retry_count()
                    trace.total_latency_ms = self._elapsed_ms(total_start)
                    return self._finalize_trace(trace)
                except Exception as fallback_exc:
                    log_failure(
                        logger,
                        logging.WARNING,
                        "generation_fallback_failed",
                        code="GENERATION_FAILED",
                        error=fallback_exc,
                    )
                    trace.request_retries += self._consume_retry_count()
                    exc = fallback_exc

            answer, trace_snapshot = self._build_fallback_answer(
                package=selected_package,
                error=exc,
                trace=trace,
                total_start=total_start,
            )
            yield answer
            return self._finalize_trace(trace_snapshot)

    def stream_with_trace(
        self,
        *,
        answer_context: AnswerContext | None = None,
        question: str = "",
        package: AnswerEvidencePackage | None = None,
        analysis: AnalysisInput = None,
        max_retries: int | None = None,
        chunk_callback: Callable[[str], None] | None = None,
    ) -> tuple[str, GenerationSnapshot]:
        chunks: list[str] = []
        generator = self.stream(
            answer_context=answer_context,
            question=question,
            package=package,
            analysis=analysis,
            max_retries=max_retries,
        )
        while True:
            try:
                chunk = next(generator)
            except StopIteration as stop:
                trace = stop.value or GenerationSnapshot()
                answer = "".join(chunks).strip() or "Streaming output completed"
                return answer, self._clone_trace(trace)
            chunks.append(chunk)
            if chunk_callback:
                chunk_callback(chunk)

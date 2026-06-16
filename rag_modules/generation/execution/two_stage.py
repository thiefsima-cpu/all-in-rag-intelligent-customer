"""Two-stage generation completion helpers."""

from __future__ import annotations

import inspect
import logging
import time

from ...answer_evidence_builder import AnswerEvidencePackage
from ...runtime import AnswerContext, GenerationSnapshot
from ..client import generation_failure_code
from ..fallback import build_evidence_only_fallback_answer, should_skip_model_fallback
from ..models import AnswerPlan

logger = logging.getLogger(__name__)


class _TwoStageCompletionMixin:
    def _generate_two_stage_with_fallback(
        self,
        *,
        answer_context: AnswerContext,
        package: AnswerEvidencePackage,
        trace: GenerationSnapshot,
        total_start: float,
        deadline: float,
    ) -> tuple[str, GenerationSnapshot]:
        try:
            answer, plan_latency_ms, compose_latency_ms, attempts_used = (
                self._run_two_stage_completion(
                    answer_context,
                    deadline=deadline,
                )
            )
            trace.status = "success"
            trace.plan_latency_ms = plan_latency_ms
            trace.compose_latency_ms = compose_latency_ms
            trace.provider_latency_ms = plan_latency_ms + compose_latency_ms
            trace.request_retries = max(0, attempts_used - 1)
            trace.total_latency_ms = self._elapsed_ms(total_start)
            return answer, self._snapshot_trace(trace)
        except Exception as exc:
            logger.warning("Two-stage generation failed: %s", exc)
            trace.request_retries += self._consume_retry_count()
            if not should_skip_model_fallback(
                exc,
                fallback_on_timeout=self.settings.fallback_on_timeout,
            ):
                try:
                    answer, direct_latency_ms, attempts_used = self._run_direct_completion(
                        answer_context,
                        deadline=deadline,
                    )
                    trace.status = "degraded"
                    trace.fallback_used = True
                    trace.failure_code = generation_failure_code(exc)
                    trace.fallback_reason = "two_stage_to_direct_model"
                    trace.direct_latency_ms = direct_latency_ms
                    trace.provider_latency_ms = (
                        trace.plan_latency_ms
                        + trace.compose_latency_ms
                        + direct_latency_ms
                    )
                    trace.request_retries += max(0, attempts_used - 1)
                    trace.total_latency_ms = self._elapsed_ms(total_start)
                    return answer, self._snapshot_trace(trace)
                except Exception as fallback_exc:
                    logger.warning("Direct model fallback also failed: %s", fallback_exc)
                    trace.request_retries += self._consume_retry_count()
                    exc = fallback_exc

            return self._build_fallback_answer(
                package=package,
                error=exc,
                trace=trace,
                total_start=total_start,
            )

    def _run_two_stage_completion(
        self,
        answer_context: AnswerContext,
        *,
        deadline: float,
    ) -> tuple[str, float, float, int]:
        plan_start = time.perf_counter()
        plan = self._build_answer_plan(
            answer_context,
            deadline=deadline,
        )
        plan_latency_ms = self._elapsed_ms(plan_start)
        retries_used = self._consume_retry_count()

        compose_start = time.perf_counter()
        answer = self.compose_from_context(
            answer_context,
            plan,
            timeout_seconds=self._remaining_timeout(
                deadline,
                self.settings.timeout_seconds,
            )
        )
        compose_latency_ms = self._elapsed_ms(compose_start)
        retries_used += self._consume_retry_count()
        return answer, plan_latency_ms, compose_latency_ms, retries_used + 1

    def _build_fallback_answer(
        self,
        *,
        package: AnswerEvidencePackage,
        error: Exception,
        trace: GenerationSnapshot,
        total_start: float,
    ) -> tuple[str, GenerationSnapshot]:
        answer = build_evidence_only_fallback_answer(
            package=package,
            error=error,
            max_items=max(1, len(package.items)),
        )
        trace.status = "degraded"
        trace.fallback_used = True
        trace.failure_code = generation_failure_code(error)
        trace.fallback_reason = trace.failure_code
        trace.total_latency_ms = self._elapsed_ms(total_start)
        trace.provider_latency_ms = max(
            trace.provider_latency_ms,
            trace.total_latency_ms,
        )
        return answer, self._snapshot_trace(trace)

    def _build_answer_plan(
        self,
        answer_context: AnswerContext,
        *,
        deadline: float,
    ) -> AnswerPlan:
        build_plan = self.planner.build_answer_plan_from_context
        parameters = inspect.signature(build_plan).parameters
        if "timeout_seconds" in parameters:
            return build_plan(
                answer_context,
                timeout_seconds=self._remaining_timeout(
                    deadline,
                    self.settings.timeout_seconds,
                ),
            )
        return build_plan(answer_context)

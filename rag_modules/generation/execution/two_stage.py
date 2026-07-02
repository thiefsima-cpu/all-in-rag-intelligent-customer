"""Two-stage generation completion helpers."""

from __future__ import annotations

import inspect
import logging
import time

from ...answer_evidence_builder import AnswerEvidencePackage
from ...contracts import RequestBudgetExceeded, RequestCancelled, RequestControl
from ...runtime import AnswerContext, GenerationSnapshot
from ...runtime.error_models import generation_error_detail
from ...safe_logging import log_failure
from ..clients import generation_failure_code
from ..fallback import build_evidence_only_fallback_answer, should_skip_model_fallback
from ..models import AnswerPlan
from .contracts import _GenerationExecutionHost

logger = logging.getLogger(__name__)


class _TwoStageCompletionMixin(_GenerationExecutionHost):
    def _generate_two_stage_with_fallback(
        self,
        *,
        answer_context: AnswerContext,
        package: AnswerEvidencePackage,
        trace: GenerationSnapshot,
        total_start: float,
        deadline: float,
        control: RequestControl | None = None,
    ) -> tuple[str, GenerationSnapshot]:
        try:
            answer, plan_latency_ms, compose_latency_ms, attempts_used = (
                self._run_two_stage_completion(
                    answer_context,
                    deadline=deadline,
                    control=control,
                )
            )
            trace.status = "success"
            trace.plan_latency_ms = plan_latency_ms
            trace.compose_latency_ms = compose_latency_ms
            trace.provider_latency_ms = plan_latency_ms + compose_latency_ms
            trace.request_retries = max(0, attempts_used - 1)
            trace.total_latency_ms = self._elapsed_ms(total_start)
            return answer, self._snapshot_trace(trace)
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
            trace.request_retries += self._consume_retry_count()
            if not should_skip_model_fallback(
                exc,
                fallback_on_timeout=self.settings.fallback_on_timeout,
            ):
                try:
                    answer, direct_latency_ms, attempts_used = self._run_direct_completion(
                        answer_context,
                        deadline=deadline,
                        control=control,
                    )
                    trace.status = "degraded"
                    trace.fallback_used = True
                    trace.failure_code = generation_failure_code(exc)
                    trace.error = generation_error_detail(exc)
                    trace.fallback_reason = "two_stage_to_direct_model"
                    trace.direct_latency_ms = direct_latency_ms
                    trace.provider_latency_ms = (
                        trace.plan_latency_ms + trace.compose_latency_ms + direct_latency_ms
                    )
                    trace.request_retries += max(0, attempts_used - 1)
                    trace.total_latency_ms = self._elapsed_ms(total_start)
                    return answer, self._snapshot_trace(trace)
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
        control: RequestControl | None = None,
    ) -> tuple[str, float, float, int]:
        if control is not None:
            control.raise_if_cancelled()
        plan_start = time.perf_counter()
        plan = self._build_answer_plan(
            answer_context,
            deadline=deadline,
            control=control,
        )
        if control is not None:
            control.raise_if_cancelled()
        plan_latency_ms = self._elapsed_ms(plan_start)
        retries_used = self._consume_retry_count()

        compose_start = time.perf_counter()
        answer = self.compose_from_context(
            answer_context,
            plan,
            timeout_seconds=self._remaining_timeout(
                deadline,
                self.settings.timeout_seconds,
            ),
            control=control,
        )
        if control is not None:
            control.raise_if_cancelled()
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
        trace.error = generation_error_detail(error)
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
        control: RequestControl | None = None,
    ) -> AnswerPlan:
        if control is not None:
            control.raise_if_cancelled()
        build_plan = self.planner.build_answer_plan_from_context
        parameters = inspect.signature(build_plan).parameters
        timeout_seconds = self._remaining_timeout(
            deadline,
            self.settings.timeout_seconds,
        )
        accepts_timeout = "timeout_seconds" in parameters
        accepts_control = "control" in parameters
        if accepts_timeout and accepts_control:
            return build_plan(
                answer_context,
                timeout_seconds=timeout_seconds,
                control=control,
            )
        if accepts_timeout:
            return build_plan(answer_context, timeout_seconds=timeout_seconds)
        if accepts_control:
            return build_plan(answer_context, control=control)
        return build_plan(answer_context)

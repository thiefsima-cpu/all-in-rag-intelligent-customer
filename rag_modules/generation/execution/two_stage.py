"""Two-stage generation completion collaborator."""

from __future__ import annotations

import inspect
import logging
import time
from dataclasses import dataclass

from ...contracts import RequestBudgetExceeded, RequestCancelled, RequestControl
from ...contracts.runtime import AnswerContext
from ...safe_logging import log_failure
from ..models import AnswerPlan, GenerationSettings
from ..planner import GenerationPlanner
from .composer import GenerationComposer
from .contracts import GenerationAttemptFailed, GenerationAttemptResult
from .direct import DirectCompletionRunner
from .fallbacks import GenerationFallbackHandler
from .timeouts import GenerationExecutionDeadline
from .usage import GenerationUsageCollector

logger = logging.getLogger(__name__)


@dataclass
class _TwoStageAttemptState:
    plan_latency_ms: float = 0.0
    compose_latency_ms: float = 0.0
    request_retries: int = 0


class TwoStageCompletionRunner:
    def __init__(
        self,
        *,
        settings: GenerationSettings,
        planner: GenerationPlanner,
        composer: GenerationComposer,
        direct_runner: DirectCompletionRunner,
        fallback_handler: GenerationFallbackHandler,
        usage_collector: GenerationUsageCollector,
    ) -> None:
        self._settings = settings
        self._planner = planner
        self._composer = composer
        self._direct_runner = direct_runner
        self._fallback_handler = fallback_handler
        self._usage_collector = usage_collector

    def run(
        self,
        answer_context: AnswerContext,
        *,
        deadline: GenerationExecutionDeadline,
        control: RequestControl | None = None,
    ) -> GenerationAttemptResult:
        state = _TwoStageAttemptState()
        try:
            return self._run_primary_attempt(
                state,
                answer_context,
                deadline=deadline,
                control=control,
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
            state.request_retries += self._usage_collector.drain_retry_count()
            if self._fallback_handler.should_attempt_model_fallback(exc):
                return self._run_direct_fallback(
                    state,
                    answer_context,
                    exc,
                    deadline=deadline,
                    control=control,
                )

            raise GenerationAttemptFailed(exc, request_retries=state.request_retries) from exc

    def _run_primary_attempt(
        self,
        state: _TwoStageAttemptState,
        answer_context: AnswerContext,
        *,
        deadline: GenerationExecutionDeadline,
        control: RequestControl | None,
    ) -> GenerationAttemptResult:
        plan, state.plan_latency_ms, plan_retries = self.run_plan_stage(
            answer_context,
            deadline=deadline,
            control=control,
        )
        state.request_retries += plan_retries
        compose_start = time.perf_counter()
        answer = self._composer.compose_from_context(
            answer_context,
            plan,
            timeout_seconds=deadline.remaining_timeout(self._settings.timeout_seconds),
            control=control,
        )
        if control is not None:
            control.raise_if_cancelled()
        state.compose_latency_ms = deadline.elapsed_ms_since(compose_start)
        state.request_retries += self._usage_collector.drain_retry_count()
        return GenerationAttemptResult(
            answer=answer,
            plan_latency_ms=state.plan_latency_ms,
            compose_latency_ms=state.compose_latency_ms,
            request_retries=state.request_retries,
        )

    def _run_direct_fallback(
        self,
        state: _TwoStageAttemptState,
        answer_context: AnswerContext,
        failure: Exception,
        *,
        deadline: GenerationExecutionDeadline,
        control: RequestControl | None,
    ) -> GenerationAttemptResult:
        try:
            direct = self._direct_runner.run(
                answer_context,
                deadline=deadline,
                control=control,
            )
            return GenerationAttemptResult(
                answer=direct.answer,
                plan_latency_ms=state.plan_latency_ms,
                compose_latency_ms=state.compose_latency_ms,
                direct_latency_ms=direct.direct_latency_ms,
                request_retries=state.request_retries + direct.request_retries,
                status="degraded",
                fallback_used=True,
                fallback_reason="two_stage_to_direct_model",
                failure=failure,
            )
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
            state.request_retries += self._usage_collector.drain_retry_count()
            raise GenerationAttemptFailed(
                fallback_exc,
                request_retries=state.request_retries,
            ) from fallback_exc

    def run_plan_stage(
        self,
        answer_context: AnswerContext,
        *,
        deadline: GenerationExecutionDeadline,
        control: RequestControl | None = None,
    ) -> tuple[AnswerPlan, float, int]:
        if control is not None:
            control.raise_if_cancelled()
        plan_start = time.perf_counter()
        plan = self._call_planner(answer_context, deadline=deadline, control=control)
        if control is not None:
            control.raise_if_cancelled()
        return (
            plan,
            deadline.elapsed_ms_since(plan_start),
            self._usage_collector.drain_retry_count(),
        )

    def _call_planner(
        self,
        answer_context: AnswerContext,
        *,
        deadline: GenerationExecutionDeadline,
        control: RequestControl | None = None,
    ) -> AnswerPlan:
        build_plan = self._planner.build_answer_plan_from_context
        parameters = inspect.signature(build_plan).parameters
        timeout_seconds = deadline.remaining_timeout(
            self._settings.timeout_seconds,
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


__all__ = ["TwoStageCompletionRunner"]

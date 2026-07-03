"""Generation execution trace recorder."""

from __future__ import annotations

from ...answer_evidence_builder import AnswerEvidencePackage
from ...runtime import GenerationSnapshot, PolicySnapshot
from ...runtime.error_models import generation_error_detail
from ..clients import generation_failure_code
from ..models import GenerationDecision, GenerationMode
from ..prompt_builder import GenerationPromptBuilder
from .contracts import GenerationAttemptResult
from .usage import GenerationUsageCollector


class GenerationTraceRecorder:
    """Own all request-local generation trace mutations."""

    def __init__(
        self,
        *,
        settings_input_cost_per_million_tokens: float,
        settings_output_cost_per_million_tokens: float,
        prompt_builder: GenerationPromptBuilder,
        usage_collector: GenerationUsageCollector,
        empty_evidence_answer: str,
    ) -> None:
        self._input_cost_per_million_tokens = max(
            0.0,
            float(settings_input_cost_per_million_tokens or 0.0),
        )
        self._output_cost_per_million_tokens = max(
            0.0,
            float(settings_output_cost_per_million_tokens or 0.0),
        )
        self._prompt_builder = prompt_builder
        self._usage_collector = usage_collector
        self._empty_evidence_answer = str(empty_evidence_answer or "")

    @staticmethod
    def clone_trace(trace: GenerationSnapshot) -> GenerationSnapshot:
        return GenerationSnapshot.from_dict(trace.to_dict())

    def snapshot_trace(self, trace: GenerationSnapshot) -> GenerationSnapshot:
        return self.clone_trace(trace)

    def policy_snapshot(self) -> PolicySnapshot:
        policy_snapshot = getattr(self._prompt_builder, "policy_snapshot", None)
        if isinstance(policy_snapshot, PolicySnapshot):
            return PolicySnapshot.from_dict(policy_snapshot.to_dict())
        return PolicySnapshot()

    def new_trace(
        self,
        decision: GenerationDecision,
        package: AnswerEvidencePackage,
        selected_package: AnswerEvidencePackage,
    ) -> GenerationSnapshot:
        return GenerationSnapshot(
            status="success",
            mode=decision.mode,
            decision_reason=decision.reason,
            total_evidence_items=len(package.items),
            selected_evidence_items=len(selected_package.items),
            policy=self.policy_snapshot(),
        )

    def record_empty_trace(
        self,
        *,
        total_latency_ms: float,
        reason: str,
    ) -> tuple[str, GenerationSnapshot]:
        trace = GenerationSnapshot(
            status="failed",
            mode=GenerationMode.EMPTY,
            decision_reason=reason,
            failure_code="no_evidence",
            total_evidence_items=0,
            selected_evidence_items=0,
            total_latency_ms=total_latency_ms,
            policy=self.policy_snapshot(),
        )
        return self._empty_evidence_answer, self.snapshot_trace(trace)

    @staticmethod
    def add_retries(trace: GenerationSnapshot, request_retries: int) -> None:
        trace.request_retries += max(0, int(request_retries or 0))

    @staticmethod
    def record_partial_plan(
        trace: GenerationSnapshot,
        *,
        plan_latency_ms: float,
        request_retries: int = 0,
    ) -> None:
        trace.plan_latency_ms = max(0.0, float(plan_latency_ms or 0.0))
        GenerationTraceRecorder.add_retries(trace, request_retries)

    @staticmethod
    def record_attempt_result(
        trace: GenerationSnapshot,
        result: GenerationAttemptResult,
        *,
        total_latency_ms: float,
    ) -> None:
        trace.status = result.status
        trace.plan_latency_ms = result.plan_latency_ms
        trace.compose_latency_ms = result.compose_latency_ms
        trace.direct_latency_ms = result.direct_latency_ms
        trace.provider_latency_ms = result.provider_latency_ms
        trace.total_latency_ms = total_latency_ms
        trace.fallback_used = result.fallback_used
        trace.fallback_reason = result.fallback_reason
        GenerationTraceRecorder.add_retries(trace, result.request_retries)
        if result.failure is not None:
            trace.failure_code = generation_failure_code(result.failure)
            trace.error = generation_error_detail(result.failure)

    @staticmethod
    def record_evidence_fallback(
        trace: GenerationSnapshot,
        *,
        error: Exception,
        total_latency_ms: float,
    ) -> None:
        trace.status = "degraded"
        trace.fallback_used = True
        trace.failure_code = generation_failure_code(error)
        trace.error = generation_error_detail(error)
        trace.fallback_reason = trace.failure_code
        trace.total_latency_ms = total_latency_ms
        trace.provider_latency_ms = max(
            trace.provider_latency_ms,
            trace.total_latency_ms,
        )

    def finalize_trace(self, trace: GenerationSnapshot) -> GenerationSnapshot:
        snapshot = self.snapshot_trace(trace)
        usage = self._usage_collector.drain_token_usage()
        snapshot.prompt_tokens += usage.prompt_tokens
        snapshot.completion_tokens += usage.completion_tokens
        reported_total = usage.total_tokens
        snapshot.total_tokens += reported_total or (usage.prompt_tokens + usage.completion_tokens)
        snapshot.estimated_cost_usd = round(
            (
                snapshot.prompt_tokens * self._input_cost_per_million_tokens
                + snapshot.completion_tokens * self._output_cost_per_million_tokens
            )
            / 1_000_000,
            8,
        )
        snapshot.token_usage_source = usage.token_usage_source
        return snapshot


__all__ = ["GenerationTraceRecorder"]

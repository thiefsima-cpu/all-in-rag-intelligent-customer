"""Generation execution trace helpers."""

from __future__ import annotations

from typing import Any

from ...answer_evidence_builder import AnswerEvidencePackage
from ...runtime import GenerationSnapshot, PolicySnapshot
from ..models import GenerationDecision, GenerationMode
from .contracts import _GenerationExecutionHost


class _GenerationTraceMixin(_GenerationExecutionHost):
    @staticmethod
    def _clone_trace(trace: GenerationSnapshot) -> GenerationSnapshot:
        return GenerationSnapshot.from_dict(trace.to_dict())

    def _snapshot_trace(self, trace: GenerationSnapshot) -> GenerationSnapshot:
        return self._clone_trace(trace)

    def _policy_snapshot(self) -> PolicySnapshot:
        policy_snapshot = getattr(self.prompt_builder, "policy_snapshot", None)
        if isinstance(policy_snapshot, PolicySnapshot):
            return PolicySnapshot.from_dict(policy_snapshot.to_dict())
        return PolicySnapshot()

    def _new_trace(
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
            policy=self._policy_snapshot(),
        )

    def _record_empty_trace(
        self, total_start: float, reason: str
    ) -> tuple[str, GenerationSnapshot]:
        trace = GenerationSnapshot(
            status="failed",
            mode=GenerationMode.EMPTY,
            decision_reason=reason,
            failure_code="no_evidence",
            total_evidence_items=0,
            selected_evidence_items=0,
            total_latency_ms=self._elapsed_ms(total_start),
            policy=self._policy_snapshot(),
        )
        return self.empty_evidence_answer, self._snapshot_trace(trace)

    def _consume_retry_count(self) -> int:
        consume = getattr(self.client_adapter, "consume_retry_count", None)
        if not callable(consume):
            return 0
        return max(0, int(consume() or 0))

    def _consume_token_usage(self) -> dict[str, Any]:
        consume = getattr(self.client_adapter, "consume_token_usage", None)
        if not callable(consume):
            return {
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
                "token_usage_source": "",
            }
        return dict(consume() or {})

    def _finalize_trace(self, trace: GenerationSnapshot) -> GenerationSnapshot:
        snapshot = self._snapshot_trace(trace)
        usage = self._consume_token_usage()
        snapshot.prompt_tokens += max(0, int(usage.get("prompt_tokens") or 0))
        snapshot.completion_tokens += max(
            0,
            int(usage.get("completion_tokens") or 0),
        )
        reported_total = max(0, int(usage.get("total_tokens") or 0))
        snapshot.total_tokens += reported_total or (
            snapshot.prompt_tokens + snapshot.completion_tokens
        )
        snapshot.estimated_cost_usd = round(
            (
                snapshot.prompt_tokens * self.settings.input_cost_per_million_tokens
                + snapshot.completion_tokens * self.settings.output_cost_per_million_tokens
            )
            / 1_000_000,
            8,
        )
        snapshot.token_usage_source = str(usage.get("token_usage_source") or "")
        return snapshot

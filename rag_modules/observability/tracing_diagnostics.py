"""Trace diagnostic classification helpers."""

from __future__ import annotations

from typing import List

from ..contracts import EvidenceDocument
from ..runtime import GenerationSnapshot, QueryDiagnostics, RouteSnapshot, RuntimeErrorDetail


class _TraceDiagnosticsMixin:
    """Classify retrieval, generation, and overall query trace state."""

    def _build_diagnostics(
        self,
        documents: List[EvidenceDocument],
        error: RuntimeErrorDetail,
        route_trace: RouteSnapshot,
        generation_trace: GenerationSnapshot,
    ) -> QueryDiagnostics:
        retrieval_bucket = self._classify_retrieval_state(documents, route_trace, error)
        generation_bucket = self._classify_generation_state(generation_trace, error)
        failure_reasons = self._failure_reasons(documents, error, route_trace)
        if generation_trace.failure_code:
            failure_reasons.append(generation_trace.failure_code)
        route_diagnostics = route_trace.diagnostics
        return QueryDiagnostics(
            retrieval_bucket=retrieval_bucket,
            generation_bucket=generation_bucket,
            overall_bucket=self._combine_buckets(
                retrieval_bucket,
                generation_bucket,
                error,
            ),
            retrieval_degraded=route_diagnostics.retrieval_degraded,
            degraded_sources=list(route_diagnostics.degraded_sources or []),
            degraded_candidates=[dict(item) for item in route_diagnostics.degraded_candidates],
            circuit_breaker_triggered=route_diagnostics.circuit_breaker_triggered,
            answer_impacted=self._answer_impacted(
                documents,
                error,
                route_trace,
                generation_trace,
            ),
            failure_reasons=failure_reasons,
        )

    @staticmethod
    def _failure_reasons(
        documents: List[EvidenceDocument],
        error: RuntimeErrorDetail,
        route_trace: RouteSnapshot,
    ) -> List[str]:
        reasons = []
        if error:
            reasons.append("answer_or_application_error")
        reasons.extend(route_trace.diagnostics.failure_reasons)
        if not documents:
            reasons.append("no_final_documents")
        stages = route_trace.stages or {}
        plan_stage = stages.get("plan")
        if plan_stage and plan_stage.details.get("used_cache") is False and route_trace.error:
            reasons.append("router_error")
        graph_stage = stages.get("graph_rag")
        if graph_stage and graph_stage.doc_count == 0:
            reasons.append("graph_empty")
        hybrid_stage = (
            stages.get("hybrid") or stages.get("hybrid_fallback") or stages.get("combined")
        )
        if hybrid_stage and hybrid_stage.doc_count == 0:
            reasons.append("hybrid_empty")
        return list(dict.fromkeys(reasons))

    @staticmethod
    def _classify_retrieval_state(
        documents: List[EvidenceDocument],
        route_trace: RouteSnapshot,
        error: RuntimeErrorDetail,
    ) -> str:
        if error and not documents:
            return "retrieval_and_generation_failed"
        if not documents:
            return "retrieval_empty"
        if route_trace.fallbacks:
            return "retrieval_used_fallback"
        if route_trace.diagnostics.retrieval_degraded:
            return "retrieval_degraded"
        stages = route_trace.stages or {}
        graph_stage = stages.get("graph_rag")
        hybrid_stage = (
            stages.get("hybrid") or stages.get("hybrid_fallback") or stages.get("combined")
        )
        if (
            graph_stage
            and hybrid_stage
            and graph_stage.doc_count == 0
            and hybrid_stage.doc_count > 0
        ):
            return "graph_sparse_hybrid_supported"
        if graph_stage and graph_stage.doc_count > 0 and len(documents) <= 1:
            return "graph_narrow"
        return "retrieval_ok"

    @staticmethod
    def _classify_generation_state(
        generation_trace: GenerationSnapshot,
        error: RuntimeErrorDetail,
    ) -> str:
        if not generation_trace.is_recorded():
            return "generation_not_recorded"
        if error:
            return "application_error"
        if generation_trace.fallback_used:
            if generation_trace.failure_code in {
                "generation_provider_timeout",
                "generation_latency_budget_exceeded",
            }:
                return "generation_timeout_fallback"
            return "generation_fallback"
        if generation_trace.status == "failed":
            return "generation_failed"
        mode = generation_trace.mode_value
        if mode == "two_stage":
            return "generation_two_stage"
        if mode == "direct":
            return "generation_direct"
        return "generation_unknown"

    @staticmethod
    def _answer_impacted(
        documents: List[EvidenceDocument],
        error: RuntimeErrorDetail,
        route_trace: RouteSnapshot,
        generation_trace: GenerationSnapshot,
    ) -> bool:
        if error:
            return True
        if route_trace.diagnostics.answer_impacted:
            return True
        if not documents:
            return True
        if generation_trace.status == "failed":
            return True
        return generation_trace.failure_code == "no_evidence"

    @staticmethod
    def _combine_buckets(
        retrieval_bucket: str,
        generation_bucket: str,
        error: RuntimeErrorDetail,
    ) -> str:
        if error:
            return "query_failed"
        if generation_bucket == "generation_timeout_fallback":
            return "latency_timeout"
        if generation_bucket == "generation_fallback":
            return "degraded_response"
        if generation_bucket == "generation_failed":
            return "query_failed"
        if retrieval_bucket in {"retrieval_empty", "retrieval_and_generation_failed"}:
            return "no_answerable_evidence"
        if (
            retrieval_bucket == "retrieval_used_fallback"
            and generation_bucket == "generation_two_stage"
        ):
            return "graph_grounded_response"
        if generation_bucket == "generation_direct":
            return "simple_grounded_response"
        return "ok"


__all__ = ["_TraceDiagnosticsMixin"]

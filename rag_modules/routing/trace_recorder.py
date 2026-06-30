"""Trace recording for query routing."""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from ..contracts import EvidenceDocument, QueryPlan, RetrievalRequest
from ..query_policy import get_query_policy
from ..runtime import PolicySnapshot, RouteSnapshot, RouteStageSnapshot
from .strategies import RouteExecutionOutcome, RouteExecutionStageResult


class RouteTraceRecorder:
    """Own RouteSnapshot construction, stage recording, and diagnostics refresh."""

    def __init__(self, *, query: str, requested_top_k: int) -> None:
        self.snapshot = RouteSnapshot(
            query=query,
            requested_top_k=requested_top_k,
            policy=PolicySnapshot.from_metadata(get_query_policy().metadata),
        )

    def record_plan(self, plan: QueryPlan, *, start_time: float) -> None:
        self.snapshot.add_stage(
            "plan",
            RouteStageSnapshot(
                latency_ms=self._elapsed_ms(start_time),
                details={
                    "used_cache": plan.used_cache,
                    "strategy": plan.strategy_value,
                    "planner_mode": plan.planner_mode_value,
                    "fallback_reason": plan.fallback_reason,
                    "query_type": plan.semantic_profile.query_type_value,
                    "relation_hits": list(plan.semantic_profile.relation_hits or []),
                    "constraint_hits": list(plan.semantic_profile.constraint_hits or []),
                    "structural_hits": list(plan.semantic_profile.structural_hits or []),
                    "semantic_score_breakdown": plan.semantic_profile.score_breakdown.to_dict(),
                },
            ),
        )

    def set_strategy(self, strategy: str) -> None:
        self.snapshot.strategy = str(strategy or "")
        self.snapshot.refresh_diagnostics()

    def set_retrieval_request(self, retrieval_request: RetrievalRequest) -> None:
        self.snapshot.retrieval_request = retrieval_request
        self.snapshot.refresh_diagnostics()

    def add_stage(
        self,
        name: str,
        *,
        start_time: float,
        documents: List[EvidenceDocument],
        extra: Optional[Any] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.snapshot.add_stage(
            name,
            self.build_stage_snapshot(
                start_time=start_time,
                documents=documents,
                extra=extra,
                details=details,
            ),
        )

    def add_stage_snapshot(self, name: str, stage: RouteStageSnapshot) -> None:
        self.snapshot.add_stage(name, stage)

    def add_stage_result(self, stage: RouteExecutionStageResult) -> None:
        self.add_stage_snapshot(
            stage.name,
            self.build_stage_snapshot_from_latency(
                latency_ms=stage.latency_ms,
                documents=stage.documents,
                extra=stage.extra,
                details=stage.details,
            ),
        )

    def record_execution_outcome(self, outcome: RouteExecutionOutcome) -> None:
        for fallback in outcome.fallbacks:
            self.add_fallback(fallback)
        for stage in outcome.stages:
            self.add_stage_result(stage)

    def add_fallback(self, reason: str) -> None:
        self.snapshot.add_fallback(reason)

    def finalize(
        self,
        *,
        total_start_time: float,
        final_doc_count: int,
        error: str = "",
    ) -> RouteSnapshot:
        self.snapshot.finalize(
            total_latency_ms=self._elapsed_ms(total_start_time),
            final_doc_count=final_doc_count,
            error=error,
        )
        return self.snapshot

    def clone_snapshot(self) -> RouteSnapshot:
        return RouteSnapshot.from_dict(self.snapshot.to_dict())

    def build_stage_snapshot(
        self,
        *,
        start_time: float,
        documents: List[EvidenceDocument],
        extra: Optional[Any] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> RouteStageSnapshot:
        return self.build_stage_snapshot_from_latency(
            latency_ms=self._elapsed_ms(start_time),
            documents=documents,
            extra=extra,
            details=details,
        )

    def build_stage_snapshot_from_latency(
        self,
        *,
        latency_ms: float,
        documents: List[EvidenceDocument],
        extra: Optional[Any] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> RouteStageSnapshot:
        payload = dict(details or {})
        if extra:
            if hasattr(extra, "to_stage_details"):
                extra_payload = extra.to_stage_details()
            elif hasattr(extra, "to_dict"):
                extra_payload = extra.to_dict()
            else:
                extra_payload = dict(extra)
            payload.update(
                {
                    key: value
                    for key, value in extra_payload.items()
                    if key not in {"latency_ms", "total_latency_ms", "doc_count", "sources"}
                }
            )
        return RouteStageSnapshot(
            latency_ms=float(latency_ms or 0.0),
            doc_count=len(documents or []),
            sources=self._count_doc_sources(documents or []),
            details=payload,
        )

    @staticmethod
    def _count_doc_sources(documents: List[EvidenceDocument]) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for doc in documents:
            metadata = doc.metadata or {}
            source = (
                doc.source
                or doc.search_method
                or doc.search_type
                or metadata.get("search_source")
                or "unknown"
            )
            counts[str(source)] = counts.get(str(source), 0) + 1
        return counts

    @staticmethod
    def _elapsed_ms(start: float) -> float:
        return round((time.perf_counter() - start) * 1000, 2)

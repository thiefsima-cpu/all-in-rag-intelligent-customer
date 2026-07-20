"""Route-level debug answer DTOs."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from ...contracts import RetrievalRequest
from ...contracts.runtime import RouteDiagnostics, RouteSnapshot, RouteStageSnapshot
from ...kernel.json_types import JsonObject
from .answer_debug_common_models import PolicySnapshotResponseModel
from .answer_mappers import (
    public_answer_error,
    public_degradation_payload,
    public_degraded_candidates,
    retrieval_request_payload,
)


class RouteStageSnapshotResponseModel(BaseModel):
    model_config = ConfigDict(extra="allow")

    latency_ms: float = 0.0
    doc_count: int = 0
    sources: dict[str, int] = Field(default_factory=dict)
    rerank_attempted: bool = False
    rerank_succeeded: bool = False
    rerank_latency_ms: float | None = None

    @classmethod
    def from_dto(cls, stage: RouteStageSnapshot) -> "RouteStageSnapshotResponseModel":
        details = dict(stage.details or {})
        raw_rerank_latency = details.get("rerank_latency_ms")
        public_details = public_degradation_payload(details)
        for field_name in (
            "rerank_attempted",
            "rerank_succeeded",
            "rerank_latency_ms",
        ):
            public_details.pop(field_name, None)
        return cls(
            latency_ms=stage.latency_ms,
            doc_count=stage.doc_count,
            sources=dict(stage.sources),
            rerank_attempted=bool(details.get("rerank_attempted", False)),
            rerank_succeeded=bool(details.get("rerank_succeeded", False)),
            rerank_latency_ms=(
                float(raw_rerank_latency)
                if isinstance(raw_rerank_latency, (bool, int, float, str))
                else None
            ),
            **public_details,
        )


class RouteDiagnosticsResponseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    used_fallback: bool = False
    fallback_count: int = 0
    planner_used_cache: Optional[bool] = None
    graph_doc_count: int = 0
    hybrid_doc_count: int = 0
    post_process_doc_count: int = 0
    retrieval_degraded: bool = False
    degraded_sources: list[str] = Field(default_factory=list)
    degraded_candidates: list[JsonObject] = Field(default_factory=list)
    circuit_breaker_triggered: bool = False
    answer_impacted: bool = False
    failure_reasons: list[str] = Field(default_factory=list)

    @classmethod
    def from_dto(cls, diagnostics: RouteDiagnostics) -> "RouteDiagnosticsResponseModel":
        return cls(
            used_fallback=diagnostics.used_fallback,
            fallback_count=diagnostics.fallback_count,
            planner_used_cache=diagnostics.planner_used_cache,
            graph_doc_count=diagnostics.graph_doc_count,
            hybrid_doc_count=diagnostics.hybrid_doc_count,
            post_process_doc_count=diagnostics.post_process_doc_count,
            retrieval_degraded=diagnostics.retrieval_degraded,
            degraded_sources=list(diagnostics.degraded_sources),
            degraded_candidates=public_degraded_candidates(diagnostics.degraded_candidates),
            circuit_breaker_triggered=diagnostics.circuit_breaker_triggered,
            answer_impacted=diagnostics.answer_impacted,
            failure_reasons=list(diagnostics.failure_reasons),
        )


class RouteSnapshotResponseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = ""
    strategy: str = ""
    requested_top_k: int = 0
    policy: PolicySnapshotResponseModel = Field(default_factory=PolicySnapshotResponseModel)
    retrieval_request: JsonObject = Field(default_factory=dict)
    stages: dict[str, RouteStageSnapshotResponseModel] = Field(default_factory=dict)
    fallbacks: list[str] = Field(default_factory=list)
    diagnostics: RouteDiagnosticsResponseModel = Field(
        default_factory=RouteDiagnosticsResponseModel
    )
    total_latency_ms: float = 0.0
    final_doc_count: int = 0
    error: JsonObject = Field(default_factory=dict)

    @classmethod
    def from_dto(cls, snapshot: RouteSnapshot) -> "RouteSnapshotResponseModel":
        return cls(
            query=snapshot.query,
            strategy=snapshot.strategy,
            requested_top_k=snapshot.requested_top_k,
            policy=PolicySnapshotResponseModel.from_dto(snapshot.policy),
            retrieval_request=(
                retrieval_request_payload(snapshot.retrieval_request)
                if isinstance(snapshot.retrieval_request, RetrievalRequest)
                else {}
            ),
            stages={
                name: RouteStageSnapshotResponseModel.from_dto(stage)
                for name, stage in snapshot.stages.items()
            },
            fallbacks=list(snapshot.fallbacks),
            diagnostics=RouteDiagnosticsResponseModel.from_dto(snapshot.diagnostics),
            total_latency_ms=snapshot.total_latency_ms,
            final_doc_count=snapshot.final_doc_count,
            error=public_answer_error(snapshot.error),
        )


__all__ = [
    "RouteDiagnosticsResponseModel",
    "RouteSnapshotResponseModel",
    "RouteStageSnapshotResponseModel",
]

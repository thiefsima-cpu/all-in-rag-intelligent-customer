"""Runtime trace debug answer DTOs."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from ...runtime import (
    AnswerTraceSnapshot,
    GenerationSnapshot,
    QueryTraceEvent,
    RetrievalTraceSnapshot,
)
from ...runtime.json_types import JsonObject, coerce_json_object
from .answer_debug_common_models import (
    ModelSuiteSnapshotResponseModel,
    PolicySnapshotResponseModel,
    QueryDiagnosticsResponseModel,
)
from .answer_debug_retrieval_models import GraphRetrievalSnapshotResponseModel
from .answer_debug_route_models import RouteSnapshotResponseModel
from .answer_mappers import public_answer_error


class GenerationSnapshotResponseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str = ""
    mode: str = ""
    policy: PolicySnapshotResponseModel = Field(default_factory=PolicySnapshotResponseModel)
    decision_reason: str = ""
    total_evidence_items: int = 0
    selected_evidence_items: int = 0
    plan_latency_ms: float = 0.0
    compose_latency_ms: float = 0.0
    direct_latency_ms: float = 0.0
    fallback_used: bool = False
    fallback_reason: str = ""
    failure_code: str = ""
    error: JsonObject = Field(default_factory=dict)
    total_latency_ms: float = 0.0
    provider_latency_ms: float = 0.0
    request_retries: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    estimated_cost_usd: float = 0.0
    token_usage_source: str = ""

    @classmethod
    def from_dto(cls, snapshot: GenerationSnapshot) -> "GenerationSnapshotResponseModel":
        return cls(
            status=snapshot.status,
            mode=snapshot.mode,
            policy=PolicySnapshotResponseModel.from_dto(snapshot.policy),
            decision_reason=snapshot.decision_reason,
            total_evidence_items=snapshot.total_evidence_items,
            selected_evidence_items=snapshot.selected_evidence_items,
            plan_latency_ms=snapshot.plan_latency_ms,
            compose_latency_ms=snapshot.compose_latency_ms,
            direct_latency_ms=snapshot.direct_latency_ms,
            fallback_used=snapshot.fallback_used,
            fallback_reason=snapshot.fallback_reason,
            failure_code=snapshot.failure_code,
            error=public_answer_error(snapshot.error),
            total_latency_ms=snapshot.total_latency_ms,
            provider_latency_ms=snapshot.provider_latency_ms,
            request_retries=snapshot.request_retries,
            prompt_tokens=snapshot.prompt_tokens,
            completion_tokens=snapshot.completion_tokens,
            total_tokens=snapshot.total_tokens,
            estimated_cost_usd=snapshot.estimated_cost_usd,
            token_usage_source=snapshot.token_usage_source,
        )


class RetrievalTraceSnapshotResponseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    doc_count: int = 0
    evidence: list[JsonObject] = Field(default_factory=list)
    route_trace: RouteSnapshotResponseModel = Field(default_factory=RouteSnapshotResponseModel)
    graph_trace: GraphRetrievalSnapshotResponseModel = Field(
        default_factory=GraphRetrievalSnapshotResponseModel
    )
    failure_reasons: list[str] = Field(default_factory=list)

    @classmethod
    def from_dto(
        cls,
        snapshot: RetrievalTraceSnapshot,
    ) -> "RetrievalTraceSnapshotResponseModel":
        return cls(
            doc_count=snapshot.doc_count,
            evidence=[coerce_json_object(item) for item in snapshot.evidence],
            route_trace=RouteSnapshotResponseModel.from_dto(snapshot.route_trace),
            graph_trace=(
                GraphRetrievalSnapshotResponseModel.from_dto(snapshot.graph_trace)
                if snapshot.graph_trace
                else GraphRetrievalSnapshotResponseModel()
            ),
            failure_reasons=list(snapshot.failure_reasons),
        )


class AnswerTraceSnapshotResponseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chars: int = 0
    preview: str = ""

    @classmethod
    def from_dto(cls, snapshot: AnswerTraceSnapshot) -> "AnswerTraceSnapshotResponseModel":
        return cls(chars=snapshot.chars, preview=snapshot.preview)


class QueryTraceEventResponseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query_id: str = ""
    timestamp: int = 0
    query: str = ""
    strategy: Optional[str] = None
    latency_ms: float = 0.0
    policy: PolicySnapshotResponseModel = Field(default_factory=PolicySnapshotResponseModel)
    plan: JsonObject = Field(default_factory=dict)
    models: ModelSuiteSnapshotResponseModel = Field(default_factory=ModelSuiteSnapshotResponseModel)
    retrieval: RetrievalTraceSnapshotResponseModel = Field(
        default_factory=RetrievalTraceSnapshotResponseModel
    )
    generation: GenerationSnapshotResponseModel = Field(
        default_factory=GenerationSnapshotResponseModel
    )
    diagnostics: QueryDiagnosticsResponseModel = Field(
        default_factory=QueryDiagnosticsResponseModel
    )
    answer: AnswerTraceSnapshotResponseModel = Field(
        default_factory=AnswerTraceSnapshotResponseModel
    )
    error: JsonObject = Field(default_factory=dict)

    @classmethod
    def from_dto(cls, event: QueryTraceEvent) -> "QueryTraceEventResponseModel":
        return cls(
            query_id=event.query_id,
            timestamp=event.timestamp,
            query=event.query,
            strategy=event.strategy,
            latency_ms=event.latency_ms,
            policy=PolicySnapshotResponseModel.from_dto(event.policy),
            plan=coerce_json_object(event.plan),
            models=ModelSuiteSnapshotResponseModel.from_dto(event.models),
            retrieval=RetrievalTraceSnapshotResponseModel.from_dto(event.retrieval),
            generation=GenerationSnapshotResponseModel.from_dto(event.generation),
            diagnostics=QueryDiagnosticsResponseModel.from_dto(event.diagnostics),
            answer=AnswerTraceSnapshotResponseModel.from_dto(event.answer),
            error=public_answer_error(event.error),
        )


__all__ = [
    "AnswerTraceSnapshotResponseModel",
    "GenerationSnapshotResponseModel",
    "QueryTraceEventResponseModel",
    "RetrievalTraceSnapshotResponseModel",
]

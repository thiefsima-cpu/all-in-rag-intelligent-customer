"""Retrieval and understanding debug answer DTOs."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from ...contracts import RetrievalRequest
from ...contracts.runtime import (
    AnswerContext,
    GraphRetrievalSnapshot,
    GraphTraceEventSnapshot,
    QueryUnderstandingSnapshot,
    RetrievalOutcome,
    RouteResolution,
)
from ...kernel.json_types import JsonObject, coerce_json_object
from .answer_debug_common_models import (
    EvidenceDocumentResponseModel,
    PolicySnapshotResponseModel,
    QueryAnalysisResponseModel,
)
from .answer_debug_route_models import RouteSnapshotResponseModel
from .answer_mappers import (
    constraints_payload,
    public_answer_error,
    public_degradation_payload,
    query_plan_payload,
    retrieval_request_payload,
    semantic_profile_payload,
)


class RetrievalOutcomeResponseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = ""
    strategy: str = ""
    doc_count: int = 0
    evidence_documents: list[EvidenceDocumentResponseModel] = Field(default_factory=list)
    route_trace: RouteSnapshotResponseModel = Field(default_factory=RouteSnapshotResponseModel)
    degradation_summary: JsonObject = Field(default_factory=dict)
    metadata: JsonObject = Field(default_factory=dict)

    @classmethod
    def from_dto(cls, outcome: RetrievalOutcome) -> "RetrievalOutcomeResponseModel":
        return cls(
            query=outcome.query,
            strategy=outcome.strategy,
            doc_count=outcome.doc_count,
            evidence_documents=[
                EvidenceDocumentResponseModel.from_dto(document)
                for document in outcome.evidence_documents
            ],
            route_trace=RouteSnapshotResponseModel.from_dto(outcome.route_trace),
            degradation_summary=public_degradation_payload(outcome.degradation_summary),
            metadata=coerce_json_object(outcome.metadata),
        )


class QueryUnderstandingSnapshotResponseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = ""
    query_plan: JsonObject = Field(default_factory=dict)
    analysis: QueryAnalysisResponseModel = Field(default_factory=QueryAnalysisResponseModel)
    constraints: JsonObject = Field(default_factory=dict)
    semantic_profile: JsonObject = Field(default_factory=dict)
    metadata: JsonObject = Field(default_factory=dict)

    @classmethod
    def from_dto(
        cls,
        snapshot: QueryUnderstandingSnapshot | None,
    ) -> "QueryUnderstandingSnapshotResponseModel":
        if snapshot is None:
            return cls()
        return cls(
            query=snapshot.query,
            query_plan=query_plan_payload(snapshot.query_plan),
            analysis=QueryAnalysisResponseModel.from_dto(snapshot.analysis),
            constraints=constraints_payload(snapshot.constraints),
            semantic_profile=semantic_profile_payload(snapshot.semantic_profile),
            metadata=coerce_json_object(snapshot.metadata),
        )


class RouteResolutionResponseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    understanding: QueryUnderstandingSnapshotResponseModel = Field(
        default_factory=QueryUnderstandingSnapshotResponseModel
    )
    retrieval: RetrievalOutcomeResponseModel = Field(default_factory=RetrievalOutcomeResponseModel)
    metadata: JsonObject = Field(default_factory=dict)

    @classmethod
    def from_dto(cls, resolution: RouteResolution) -> "RouteResolutionResponseModel":
        return cls(
            understanding=QueryUnderstandingSnapshotResponseModel.from_dto(
                resolution.understanding
            ),
            retrieval=RetrievalOutcomeResponseModel.from_dto(resolution.retrieval),
            metadata=coerce_json_object(resolution.metadata),
        )


class AnswerContextResponseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = ""
    retrieval: RetrievalOutcomeResponseModel = Field(default_factory=RetrievalOutcomeResponseModel)
    analysis: QueryAnalysisResponseModel = Field(default_factory=QueryAnalysisResponseModel)
    understanding: QueryUnderstandingSnapshotResponseModel = Field(
        default_factory=QueryUnderstandingSnapshotResponseModel
    )
    evidence_package: JsonObject = Field(default_factory=dict)
    metadata: JsonObject = Field(default_factory=dict)

    @classmethod
    def from_dto(cls, context: AnswerContext) -> "AnswerContextResponseModel":
        return cls(
            question=context.question,
            retrieval=RetrievalOutcomeResponseModel.from_dto(context.retrieval),
            analysis=QueryAnalysisResponseModel.from_dto(context.analysis),
            understanding=QueryUnderstandingSnapshotResponseModel.from_dto(context.understanding),
            evidence_package=coerce_json_object(context.evidence_package),
            metadata=coerce_json_object(context.metadata),
        )


class GraphTraceEventSnapshotResponseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = ""
    status: str = "ok"
    latency_ms: float = 0.0
    details: JsonObject = Field(default_factory=dict)

    @classmethod
    def from_dto(
        cls,
        event: GraphTraceEventSnapshot,
    ) -> "GraphTraceEventSnapshotResponseModel":
        return cls(
            name=event.name,
            status=event.status,
            latency_ms=event.latency_ms,
            details=coerce_json_object(event.details),
        )


class GraphRetrievalSnapshotResponseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = ""
    strategy: str = "graph_rag"
    requested_top_k: int = 0
    policy: PolicySnapshotResponseModel = Field(default_factory=PolicySnapshotResponseModel)
    retrieval_request: JsonObject = Field(default_factory=dict)
    query_type: str = ""
    source_entities: list[str] = Field(default_factory=list)
    target_entities: list[str] = Field(default_factory=list)
    relation_types: list[str] = Field(default_factory=list)
    sub_questions: list[str] = Field(default_factory=list)
    path_count: int = 0
    subgraph_count: int = 0
    reasoning_patterns: list[str] = Field(default_factory=list)
    reasoning_chain_count: int = 0
    evidence_unit_count: int = 0
    doc_count: int = 0
    retrieval_plan: JsonObject = Field(default_factory=dict)
    events: list[GraphTraceEventSnapshotResponseModel] = Field(default_factory=list)
    total_latency_ms: float = 0.0
    error: JsonObject = Field(default_factory=dict)

    @classmethod
    def from_dto(
        cls,
        snapshot: GraphRetrievalSnapshot,
    ) -> "GraphRetrievalSnapshotResponseModel":
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
            query_type=snapshot.query_type,
            source_entities=list(snapshot.source_entities),
            target_entities=list(snapshot.target_entities),
            relation_types=list(snapshot.relation_types),
            sub_questions=list(snapshot.sub_questions),
            path_count=snapshot.path_count,
            subgraph_count=snapshot.subgraph_count,
            reasoning_patterns=list(snapshot.reasoning_patterns),
            reasoning_chain_count=snapshot.reasoning_chain_count,
            evidence_unit_count=snapshot.evidence_unit_count,
            doc_count=snapshot.doc_count,
            retrieval_plan=coerce_json_object(snapshot.retrieval_plan),
            events=[
                GraphTraceEventSnapshotResponseModel.from_dto(event) for event in snapshot.events
            ],
            total_latency_ms=snapshot.total_latency_ms,
            error=public_answer_error(snapshot.error),
        )


__all__ = [
    "AnswerContextResponseModel",
    "GraphRetrievalSnapshotResponseModel",
    "GraphTraceEventSnapshotResponseModel",
    "QueryUnderstandingSnapshotResponseModel",
    "RetrievalOutcomeResponseModel",
    "RouteResolutionResponseModel",
]

"""Shared debug answer DTOs."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from ...contracts import EvidenceDocument
from ...contracts.runtime import ModelSuiteSnapshot, PolicySnapshot, QueryAnalysis, QueryDiagnostics
from ...kernel.json_types import JsonObject, coerce_json_object
from .answer_mappers import public_degraded_candidates, semantic_profile_payload


class QueryAnalysisResponseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query_complexity: float = 0.0
    relationship_intensity: float = 0.0
    reasoning_required: bool = False
    entity_count: int = 0
    recommended_strategy: str = ""
    confidence: float = 0.0
    reasoning: str = ""
    semantic_profile: JsonObject = Field(default_factory=dict)

    @classmethod
    def from_dto(cls, analysis: QueryAnalysis | None) -> "QueryAnalysisResponseModel":
        if analysis is None:
            return cls()
        return cls(
            query_complexity=analysis.query_complexity,
            relationship_intensity=analysis.relationship_intensity,
            reasoning_required=analysis.reasoning_required,
            entity_count=analysis.entity_count,
            recommended_strategy=analysis.strategy_name,
            confidence=analysis.confidence,
            reasoning=analysis.reasoning,
            semantic_profile=semantic_profile_payload(analysis.semantic_profile),
        )


class EvidenceDocumentResponseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str = ""
    entity_id: str = ""
    entity_name: str = ""
    entity_type: str = ""
    node_id: str = ""
    node_type: str = ""
    score: float = 0.0
    search_type: str = ""
    search_method: str = ""
    retrieval_level: str = ""
    doc_id: str = ""
    source: str = "unknown"
    evidence_type: str = "text"
    matched_terms: list[str] = Field(default_factory=list)
    graph_evidence: JsonObject = Field(default_factory=dict)
    domain_graph_evidence: JsonObject = Field(default_factory=dict)
    constraint_evidence: JsonObject = Field(default_factory=dict)
    evidence_units: list[JsonObject] = Field(default_factory=list)
    route_strategy: str = ""
    metadata: JsonObject = Field(default_factory=dict)

    @classmethod
    def from_dto(cls, document: EvidenceDocument) -> "EvidenceDocumentResponseModel":
        return cls(
            content=document.content,
            entity_id=document.entity_id,
            entity_name=document.entity_name,
            entity_type=document.entity_type,
            node_id=document.node_id,
            node_type=document.node_type,
            score=document.score,
            search_type=document.search_type,
            search_method=document.search_method,
            retrieval_level=document.retrieval_level,
            doc_id=document.doc_id,
            source=document.source,
            evidence_type=document.evidence_type,
            matched_terms=list(document.matched_terms),
            graph_evidence=coerce_json_object(document.graph_evidence),
            domain_graph_evidence=coerce_json_object(document.domain_graph_evidence),
            constraint_evidence=coerce_json_object(document.constraint_evidence),
            evidence_units=[coerce_json_object(item) for item in document.evidence_units],
            route_strategy=document.route_strategy,
            metadata=coerce_json_object(document.metadata),
        )


class PolicySnapshotResponseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = ""
    policy_version: str = ""
    prompt_version: str = ""
    policy_hash: str = ""
    prompt_hash: str = ""
    bundle_name: str = ""

    @classmethod
    def from_dto(cls, snapshot: PolicySnapshot) -> "PolicySnapshotResponseModel":
        return cls(
            schema_version=snapshot.schema_version,
            policy_version=snapshot.policy_version,
            prompt_version=snapshot.prompt_version,
            policy_hash=snapshot.policy_hash,
            prompt_hash=snapshot.prompt_hash,
            bundle_name=snapshot.bundle_name,
        )


class QueryDiagnosticsResponseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    retrieval_bucket: str = ""
    generation_bucket: str = ""
    overall_bucket: str = ""
    retrieval_degraded: bool = False
    degraded_sources: list[str] = Field(default_factory=list)
    degraded_candidates: list[JsonObject] = Field(default_factory=list)
    circuit_breaker_triggered: bool = False
    answer_impacted: bool = False
    failure_reasons: list[str] = Field(default_factory=list)

    @classmethod
    def from_dto(cls, diagnostics: QueryDiagnostics) -> "QueryDiagnosticsResponseModel":
        return cls(
            retrieval_bucket=diagnostics.retrieval_bucket,
            generation_bucket=diagnostics.generation_bucket,
            overall_bucket=diagnostics.overall_bucket,
            retrieval_degraded=diagnostics.retrieval_degraded,
            degraded_sources=list(diagnostics.degraded_sources),
            degraded_candidates=public_degraded_candidates(diagnostics.degraded_candidates),
            circuit_breaker_triggered=diagnostics.circuit_breaker_triggered,
            answer_impacted=diagnostics.answer_impacted,
            failure_reasons=list(diagnostics.failure_reasons),
        )


class ModelSuiteSnapshotResponseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    llm: str = ""
    embedding: str = ""
    rerank: str = ""

    @classmethod
    def from_dto(cls, snapshot: ModelSuiteSnapshot) -> "ModelSuiteSnapshotResponseModel":
        return cls(
            llm=snapshot.llm,
            embedding=snapshot.embedding,
            rerank=snapshot.rerank,
        )


__all__ = [
    "EvidenceDocumentResponseModel",
    "ModelSuiteSnapshotResponseModel",
    "PolicySnapshotResponseModel",
    "QueryAnalysisResponseModel",
    "QueryDiagnosticsResponseModel",
]

"""Pydantic models for answer API requests, responses, and SSE events."""

from __future__ import annotations

from collections.abc import Mapping
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ...app.services.answer_models import (
    QuestionAnswerDiagnostics,
    QuestionAnswerGrounding,
    QuestionAnswerResponse,
    QuestionAnswerSummary,
    QuestionAnswerTraces,
)
from ...domain.shared.query_constraints import QueryConstraints
from ...query_understanding import QueryPlan, QuerySemanticProfile, QuerySemanticScoreBreakdown
from ...retrieval.contracts import EvidenceDocument, RetrievalRequest
from ...runtime import (
    AnswerContext,
    AnswerTraceSnapshot,
    GenerationSnapshot,
    GraphRetrievalSnapshot,
    GraphTraceEventSnapshot,
    ModelSuiteSnapshot,
    QueryAnalysis,
    QueryDiagnostics,
    QueryTraceEvent,
    QueryUnderstandingSnapshot,
    RetrievalOutcome,
    RetrievalTraceSnapshot,
    RouteDiagnostics,
    RouteResolution,
    RouteSnapshot,
    RouteStageSnapshot,
)
from ...runtime.json_types import JsonObject, coerce_json_object
from .error_models import ErrorCode, ErrorResponseModel, build_error_model

MAX_QUESTION_CHARS = 4000


def _constraints_payload(value: QueryConstraints) -> JsonObject:
    return {
        "include_terms": list(value.include_terms),
        "exclude_terms": list(value.exclude_terms),
        "ingredients": list(value.ingredients),
        "excluded_ingredients": list(value.excluded_ingredients),
        "cuisine_terms": list(value.cuisine_terms),
        "excluded_cuisine_terms": list(value.excluded_cuisine_terms),
        "category_terms": list(value.category_terms),
        "health_terms": list(value.health_terms),
        "preference_terms": list(value.preference_terms),
        "time": {
            "max_total_minutes": value.max_total_minutes,
            "max_prep_minutes": value.max_prep_minutes,
            "max_cook_minutes": value.max_cook_minutes,
        },
        "needs_recipe_recommendation": value.needs_recipe_recommendation,
    }


def _score_breakdown_payload(value: QuerySemanticScoreBreakdown) -> JsonObject:
    return {
        "relation_hit_count": value.relation_hit_count,
        "constraint_hit_count": value.constraint_hit_count,
        "structural_hit_count": value.structural_hit_count,
        "fast_rule_hit_count": value.fast_rule_hit_count,
        "length_factor": value.length_factor,
        "lexical_relationship_intensity": value.lexical_relationship_intensity,
        "relation_hit_intensity_boost": value.relation_hit_intensity_boost,
        "lexical_complexity": value.lexical_complexity,
        "relation_hit_complexity_boost": value.relation_hit_complexity_boost,
        "relationship_intensity": value.relationship_intensity,
        "complexity": value.complexity,
    }


def _semantic_profile_payload(value: QuerySemanticProfile) -> JsonObject:
    return {
        "query": value.query,
        "query_type": value.query_type,
        "source_entities": list(value.source_entities),
        "target_entities": list(value.target_entities),
        "relation_types": list(value.relation_types),
        "entity_keywords": list(value.entity_keywords),
        "topic_keywords": list(value.topic_keywords),
        "constraints": coerce_json_object(value.constraints),
        "complexity": value.complexity,
        "relationship_intensity": value.relationship_intensity,
        "reasoning_required": value.reasoning_required,
        "needs_recipe_recommendation": value.needs_recipe_recommendation,
        "recommendation_hits": list(value.recommendation_hits),
        "relation_hits": list(value.relation_hits),
        "constraint_hits": list(value.constraint_hits),
        "structural_hits": list(value.structural_hits),
        "fast_rule_hits": list(value.fast_rule_hits),
        "score_breakdown": _score_breakdown_payload(value.score_breakdown),
    }


def _query_plan_payload(value: QueryPlan) -> JsonObject:
    return {
        "query": value.query,
        "intent": value.intent,
        "complexity": value.complexity,
        "relationship_intensity": value.relationship_intensity,
        "reasoning_required": value.reasoning_required,
        "strategy": value.strategy,
        "confidence": value.confidence,
        "reasoning": value.reasoning,
        "entity_keywords": list(value.entity_keywords),
        "topic_keywords": list(value.topic_keywords),
        "graph_query_type": value.graph_query_type,
        "source_entities": list(value.source_entities),
        "target_entities": list(value.target_entities),
        "relation_types": list(value.relation_types),
        "max_depth": value.max_depth,
        "constraints": _constraints_payload(value.constraints),
        "needs_recipe_recommendation": value.needs_recipe_recommendation,
        "answer_style": value.answer_style,
        "planner_version": value.planner_version,
        "used_cache": value.used_cache,
        "fallback_reason": value.fallback_reason,
        "planner_mode": value.planner_mode,
        "semantic_profile": _semantic_profile_payload(value.semantic_profile),
        "validation_errors": list(value.validation_errors),
    }


def _retrieval_request_payload(value: RetrievalRequest | None) -> JsonObject:
    if value is None:
        return {}
    return {
        "query": value.query,
        "top_k": value.top_k,
        "candidate_k": value.candidate_k,
        "strategy": value.strategy,
        "constraints": _constraints_payload(value.effective_constraints),
        "query_plan": _query_plan_payload(value.query_plan) if value.query_plan else None,
        "entity_keywords": list(value.entity_keywords),
        "topic_keywords": list(value.topic_keywords),
        "metadata": coerce_json_object(value.metadata),
    }


def _public_answer_error(value: str) -> str:
    return ErrorCode.ANSWER_FAILED.value if str(value or "") else ""


class AnswerStreamEventType(str, Enum):
    message = "message"
    chunk = "chunk"
    result = "result"
    error = "error"
    done = "done"


class AnswerRequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1, max_length=MAX_QUESTION_CHARS)
    stream: bool = Field(
        default=False,
        description="Compatibility flag. Prefer POST /answers/stream for SSE responses.",
        deprecated=True,
    )
    explain_routing: bool = Field(
        default=False,
        description="Include route-explanation messages in the response diagnostics or SSE events.",
    )

    @field_validator("question", mode="before")
    @classmethod
    def normalize_question(cls, value):
        if not isinstance(value, str):
            return value
        normalized = value.strip()
        if "\x00" in normalized:
            raise ValueError("question must not contain NUL characters")
        return normalized


class AnswerStreamRequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1, max_length=MAX_QUESTION_CHARS)
    explain_routing: bool = Field(
        default=False,
        description="Include route-explanation messages in the SSE event stream.",
    )

    @field_validator("question", mode="before")
    @classmethod
    def normalize_question(cls, value):
        return AnswerRequestModel.normalize_question(value)


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
            semantic_profile=_semantic_profile_payload(analysis.semantic_profile),
        )


class EvidenceDocumentResponseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str = ""
    node_id: str = ""
    recipe_name: str = ""
    node_type: str = ""
    score: float = 0.0
    search_type: str = ""
    search_method: str = ""
    retrieval_level: str = ""
    doc_id: str = ""
    recipe_id: str = ""
    source: str = "unknown"
    evidence_type: str = "text"
    matched_terms: list[str] = Field(default_factory=list)
    graph_evidence: JsonObject = Field(default_factory=dict)
    recipe_graph_evidence: JsonObject = Field(default_factory=dict)
    constraint_evidence: JsonObject = Field(default_factory=dict)
    evidence_units: list[JsonObject] = Field(default_factory=list)
    route_strategy: str = ""
    metadata: JsonObject = Field(default_factory=dict)

    @classmethod
    def from_dto(cls, document: EvidenceDocument) -> "EvidenceDocumentResponseModel":
        return cls(
            content=document.content,
            node_id=document.node_id,
            recipe_name=document.recipe_name,
            node_type=document.node_type,
            score=document.score,
            search_type=document.search_type,
            search_method=document.search_method,
            retrieval_level=document.retrieval_level,
            doc_id=document.doc_id,
            recipe_id=document.recipe_id,
            source=document.source,
            evidence_type=document.evidence_type,
            matched_terms=list(document.matched_terms),
            graph_evidence=coerce_json_object(document.graph_evidence),
            recipe_graph_evidence=coerce_json_object(document.recipe_graph_evidence),
            constraint_evidence=coerce_json_object(document.constraint_evidence),
            evidence_units=[coerce_json_object(item) for item in document.evidence_units],
            route_strategy=document.route_strategy,
            metadata=coerce_json_object(document.metadata),
        )


class RouteStageSnapshotResponseModel(BaseModel):
    model_config = ConfigDict(extra="allow")

    latency_ms: float = 0.0
    doc_count: int = 0
    sources: dict[str, int] = Field(default_factory=dict)

    @classmethod
    def from_dto(cls, stage: RouteStageSnapshot) -> "RouteStageSnapshotResponseModel":
        return cls(
            latency_ms=stage.latency_ms,
            doc_count=stage.doc_count,
            sources=dict(stage.sources),
            **coerce_json_object(stage.details),
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
            degraded_candidates=[
                coerce_json_object(item) for item in diagnostics.degraded_candidates
            ],
            circuit_breaker_triggered=diagnostics.circuit_breaker_triggered,
            answer_impacted=diagnostics.answer_impacted,
            failure_reasons=list(diagnostics.failure_reasons),
        )


class RouteSnapshotResponseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = ""
    strategy: str = ""
    requested_top_k: int = 0
    retrieval_request: JsonObject = Field(default_factory=dict)
    stages: dict[str, RouteStageSnapshotResponseModel] = Field(default_factory=dict)
    fallbacks: list[str] = Field(default_factory=list)
    diagnostics: RouteDiagnosticsResponseModel = Field(
        default_factory=RouteDiagnosticsResponseModel
    )
    total_latency_ms: float = 0.0
    final_doc_count: int = 0
    error: str = ""

    @classmethod
    def from_dto(cls, snapshot: RouteSnapshot) -> "RouteSnapshotResponseModel":
        return cls(
            query=snapshot.query,
            strategy=snapshot.strategy,
            requested_top_k=snapshot.requested_top_k,
            retrieval_request=(
                _retrieval_request_payload(snapshot.retrieval_request)
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
            error=_public_answer_error(snapshot.error),
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
            degradation_summary=coerce_json_object(outcome.degradation_summary),
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
            query_plan=_query_plan_payload(snapshot.query_plan),
            analysis=QueryAnalysisResponseModel.from_dto(snapshot.analysis),
            constraints=_constraints_payload(snapshot.constraints),
            semantic_profile=_semantic_profile_payload(snapshot.semantic_profile),
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
            degraded_candidates=[
                coerce_json_object(item) for item in diagnostics.degraded_candidates
            ],
            circuit_breaker_triggered=diagnostics.circuit_breaker_triggered,
            answer_impacted=diagnostics.answer_impacted,
            failure_reasons=list(diagnostics.failure_reasons),
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
    error: str = ""

    @classmethod
    def from_dto(
        cls,
        snapshot: GraphRetrievalSnapshot,
    ) -> "GraphRetrievalSnapshotResponseModel":
        return cls(
            query=snapshot.query,
            strategy=snapshot.strategy,
            requested_top_k=snapshot.requested_top_k,
            retrieval_request=(
                _retrieval_request_payload(snapshot.retrieval_request)
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
            error=_public_answer_error(snapshot.error),
        )


class GenerationSnapshotResponseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str = ""
    mode: str = ""
    decision_reason: str = ""
    total_evidence_items: int = 0
    selected_evidence_items: int = 0
    plan_latency_ms: float = 0.0
    compose_latency_ms: float = 0.0
    direct_latency_ms: float = 0.0
    fallback_used: bool = False
    fallback_reason: str = ""
    failure_code: str = ""
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
            decision_reason=snapshot.decision_reason,
            total_evidence_items=snapshot.total_evidence_items,
            selected_evidence_items=snapshot.selected_evidence_items,
            plan_latency_ms=snapshot.plan_latency_ms,
            compose_latency_ms=snapshot.compose_latency_ms,
            direct_latency_ms=snapshot.direct_latency_ms,
            fallback_used=snapshot.fallback_used,
            fallback_reason=snapshot.fallback_reason,
            failure_code=snapshot.failure_code,
            total_latency_ms=snapshot.total_latency_ms,
            provider_latency_ms=snapshot.provider_latency_ms,
            request_retries=snapshot.request_retries,
            prompt_tokens=snapshot.prompt_tokens,
            completion_tokens=snapshot.completion_tokens,
            total_tokens=snapshot.total_tokens,
            estimated_cost_usd=snapshot.estimated_cost_usd,
            token_usage_source=snapshot.token_usage_source,
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
    error: str = ""

    @classmethod
    def from_dto(cls, event: QueryTraceEvent) -> "QueryTraceEventResponseModel":
        return cls(
            query_id=event.query_id,
            timestamp=event.timestamp,
            query=event.query,
            strategy=event.strategy,
            latency_ms=event.latency_ms,
            plan=coerce_json_object(event.plan),
            models=ModelSuiteSnapshotResponseModel.from_dto(event.models),
            retrieval=RetrievalTraceSnapshotResponseModel.from_dto(event.retrieval),
            generation=GenerationSnapshotResponseModel.from_dto(event.generation),
            diagnostics=QueryDiagnosticsResponseModel.from_dto(event.diagnostics),
            answer=AnswerTraceSnapshotResponseModel.from_dto(event.answer),
            error=_public_answer_error(event.error),
        )


class AnswerSummaryModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answer: str
    status: str = "success"
    strategy: str = ""
    latency_ms: float = 0.0
    doc_count: int = 0
    has_evidence: bool = False
    fallback_used: bool = False
    failure_code: str = ""
    provider_latency_ms: float = 0.0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    estimated_cost_usd: float = 0.0
    token_usage_source: str = ""
    error: str = ""

    @classmethod
    def from_dto(cls, summary: QuestionAnswerSummary) -> "AnswerSummaryModel":
        return cls(
            answer=summary.answer,
            status=summary.status,
            strategy=summary.strategy,
            latency_ms=summary.latency_ms,
            doc_count=summary.doc_count,
            has_evidence=summary.has_evidence,
            fallback_used=summary.fallback_used,
            failure_code=summary.failure_code,
            provider_latency_ms=summary.provider_latency_ms,
            prompt_tokens=summary.prompt_tokens,
            completion_tokens=summary.completion_tokens,
            total_tokens=summary.total_tokens,
            estimated_cost_usd=summary.estimated_cost_usd,
            token_usage_source=summary.token_usage_source,
            error=_public_answer_error(summary.error),
        )


class AnswerGroundingModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    retrieval_outcome: RetrievalOutcomeResponseModel = Field(
        default_factory=RetrievalOutcomeResponseModel
    )
    answer_context: AnswerContextResponseModel = Field(default_factory=AnswerContextResponseModel)
    route_resolution: RouteResolutionResponseModel = Field(
        default_factory=RouteResolutionResponseModel
    )
    evidence_documents: list[EvidenceDocumentResponseModel] = Field(default_factory=list)

    @classmethod
    def from_dto(cls, grounding: QuestionAnswerGrounding) -> "AnswerGroundingModel":
        return cls(
            retrieval_outcome=RetrievalOutcomeResponseModel.from_dto(grounding.retrieval_outcome),
            answer_context=AnswerContextResponseModel.from_dto(grounding.answer_context),
            route_resolution=RouteResolutionResponseModel.from_dto(grounding.route_resolution),
            evidence_documents=[
                EvidenceDocumentResponseModel.from_dto(document)
                for document in grounding.evidence_documents
            ],
        )


class AnswerDiagnosticsModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    analysis: QueryAnalysisResponseModel = Field(default_factory=QueryAnalysisResponseModel)
    diagnostics: QueryDiagnosticsResponseModel = Field(
        default_factory=QueryDiagnosticsResponseModel
    )

    @classmethod
    def from_dto(cls, diagnostics: QuestionAnswerDiagnostics) -> "AnswerDiagnosticsModel":
        return cls(
            analysis=QueryAnalysisResponseModel.from_dto(diagnostics.analysis),
            diagnostics=QueryDiagnosticsResponseModel.from_dto(diagnostics.diagnostics),
        )


class AnswerTracesModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    route_trace: RouteSnapshotResponseModel = Field(default_factory=RouteSnapshotResponseModel)
    graph_trace: GraphRetrievalSnapshotResponseModel = Field(
        default_factory=GraphRetrievalSnapshotResponseModel
    )
    generation_trace: GenerationSnapshotResponseModel = Field(
        default_factory=GenerationSnapshotResponseModel
    )
    trace_event: QueryTraceEventResponseModel = Field(default_factory=QueryTraceEventResponseModel)

    @classmethod
    def from_dto(cls, traces: QuestionAnswerTraces) -> "AnswerTracesModel":
        return cls(
            route_trace=RouteSnapshotResponseModel.from_dto(traces.route_trace),
            graph_trace=GraphRetrievalSnapshotResponseModel.from_dto(traces.graph_trace),
            generation_trace=GenerationSnapshotResponseModel.from_dto(traces.generation_trace),
            trace_event=QueryTraceEventResponseModel.from_dto(traces.trace_event),
        )


class AnswerPayloadModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: AnswerSummaryModel
    grounding: AnswerGroundingModel
    diagnostics: AnswerDiagnosticsModel
    traces: AnswerTracesModel

    @classmethod
    def from_payload(cls, payload: Mapping[str, object]) -> "AnswerPayloadModel":
        return cls.model_validate(dict(payload or {}))

    @classmethod
    def from_dto(cls, response: QuestionAnswerResponse) -> "AnswerPayloadModel":
        return cls(
            summary=AnswerSummaryModel.from_dto(response.summary),
            grounding=AnswerGroundingModel.from_dto(response.grounding),
            diagnostics=AnswerDiagnosticsModel.from_dto(response.diagnostics),
            traces=AnswerTracesModel.from_dto(response.traces),
        )


class AnswerResponseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    response: AnswerPayloadModel


class AnswerStreamMessageDataModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str


class AnswerStreamChunkDataModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str


class AnswerStreamResultDataModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    response: AnswerPayloadModel


class AnswerStreamDoneDataModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ok: bool = True


class AnswerStreamEventModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event: AnswerStreamEventType
    data: (
        AnswerStreamMessageDataModel
        | AnswerStreamChunkDataModel
        | AnswerStreamResultDataModel
        | ErrorResponseModel
        | AnswerStreamDoneDataModel
    )

    @classmethod
    def message(cls, message: str) -> "AnswerStreamEventModel":
        return cls(
            event=AnswerStreamEventType.message,
            data=AnswerStreamMessageDataModel(message=str(message)),
        )

    @classmethod
    def chunk(cls, content: str) -> "AnswerStreamEventModel":
        return cls(
            event=AnswerStreamEventType.chunk,
            data=AnswerStreamChunkDataModel(content=str(content)),
        )

    @classmethod
    def result(cls, response: AnswerPayloadModel) -> "AnswerStreamEventModel":
        return cls(
            event=AnswerStreamEventType.result,
            data=AnswerStreamResultDataModel(response=response),
        )

    @classmethod
    def error(
        cls,
        *,
        code: ErrorCode,
        request_id: str,
    ) -> "AnswerStreamEventModel":
        return cls(
            event=AnswerStreamEventType.error,
            data=build_error_model(code, request_id=request_id),
        )

    @classmethod
    def done(cls) -> "AnswerStreamEventModel":
        return cls(
            event=AnswerStreamEventType.done,
            data=AnswerStreamDoneDataModel(ok=True),
        )


__all__ = [
    "MAX_QUESTION_CHARS",
    "AnswerContextResponseModel",
    "AnswerDiagnosticsModel",
    "AnswerGroundingModel",
    "AnswerPayloadModel",
    "AnswerRequestModel",
    "AnswerResponseModel",
    "AnswerStreamChunkDataModel",
    "AnswerStreamDoneDataModel",
    "AnswerStreamEventModel",
    "AnswerStreamEventType",
    "AnswerStreamMessageDataModel",
    "AnswerStreamRequestModel",
    "AnswerStreamResultDataModel",
    "AnswerSummaryModel",
    "AnswerTraceSnapshotResponseModel",
    "AnswerTracesModel",
    "EvidenceDocumentResponseModel",
    "GenerationSnapshotResponseModel",
    "GraphRetrievalSnapshotResponseModel",
    "GraphTraceEventSnapshotResponseModel",
    "ModelSuiteSnapshotResponseModel",
    "QueryAnalysisResponseModel",
    "QueryDiagnosticsResponseModel",
    "QueryTraceEventResponseModel",
    "QueryUnderstandingSnapshotResponseModel",
    "RetrievalOutcomeResponseModel",
    "RetrievalTraceSnapshotResponseModel",
    "RouteDiagnosticsResponseModel",
    "RouteResolutionResponseModel",
    "RouteSnapshotResponseModel",
    "RouteStageSnapshotResponseModel",
]

"""Pydantic models for the FastAPI surface."""

from __future__ import annotations

from collections.abc import Mapping
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ...runtime.json_types import JsonObject

MAX_QUESTION_CHARS = 4000


class DiagnosticsMode(str, Enum):
    build = "build"
    serve = "serve"


class AnswerStreamEventType(str, Enum):
    message = "message"
    chunk = "chunk"
    result = "result"
    error = "error"
    done = "done"


class BuildJobType(str, Enum):
    build = "build"
    rebuild = "rebuild"


class BuildJobStatus(str, Enum):
    queued = "queued"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"


class HealthResponseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str = "ok"
    build_initialized: bool
    serving_initialized: bool
    artifacts_ready: bool
    system_ready: bool
    retrieval_engines_initialized: bool
    manifest_health: str


class OperationResponseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ok: bool = True
    message: str
    diagnostics: Optional[JsonObject] = None
    stats: Optional[JsonObject] = None


class ArtifactManifestResponseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stage: str = ""
    health: str = ""
    updated_at: str = ""
    collection_name: str = ""
    manifest_path: str = ""
    documents_path: str = ""
    chunks_path: str = ""
    total_documents: int = 0
    total_chunks: int = 0
    vector_rows: int = 0
    cache_hit: bool = False
    last_error: str = ""
    build_metadata: JsonObject = Field(default_factory=dict)
    manifest_version: int = 0
    index_version: str = ""
    collection_base_name: str = ""
    collection_slot: str = ""
    previous_collection_name: str = ""
    published_at: str = ""


class ArtifactRegistryResponseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    active: ArtifactManifestResponseModel
    candidate: Optional[ArtifactManifestResponseModel] = None
    versions: list[int] = Field(default_factory=list)


class ModelSuiteResponseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    embedding_model: str = ""
    llm_model: str = ""
    rerank_model: str = ""


class RouteStatsResponseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    traditional_count: int = 0
    graph_rag_count: int = 0
    combined_count: int = 0
    total_queries: int = 0
    traditional_ratio: Optional[float] = None
    graph_rag_ratio: Optional[float] = None
    combined_ratio: Optional[float] = None


class StartupDiagnosticsPayloadModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: str = ""
    llm_model: str = ""
    embedding_model: str = ""
    rerank_model: str = ""
    trace_enabled: bool = False
    trace_path: str = ""
    trace_stats: JsonObject = Field(default_factory=dict)
    build_initialized: bool = False
    serving_initialized: bool = False
    artifacts_ready: bool = False
    system_ready: bool = False
    retrieval_engines_initialized: bool = False
    manifest: ArtifactManifestResponseModel = Field(default_factory=ArtifactManifestResponseModel)


class DiagnosticsResponseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    diagnostics: StartupDiagnosticsPayloadModel


class SystemStatsPayloadModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    initialized: bool = False
    build_initialized: bool = False
    serving_initialized: bool = False
    artifacts_ready: bool = False
    ready: bool = False
    models: ModelSuiteResponseModel = Field(default_factory=ModelSuiteResponseModel)
    trace_stats: JsonObject = Field(default_factory=dict)
    retrieval_runtime_profile: JsonObject = Field(default_factory=dict)
    artifact_manifest: ArtifactManifestResponseModel = Field(
        default_factory=ArtifactManifestResponseModel
    )
    data_stats: JsonObject = Field(default_factory=dict)
    index_stats: JsonObject = Field(default_factory=dict)
    route_stats: RouteStatsResponseModel = Field(default_factory=RouteStatsResponseModel)


class StatsResponseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stats: SystemStatsPayloadModel


class BuildJobResultModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str = ""
    diagnostics: Optional[JsonObject] = None
    stats: Optional[JsonObject] = None


class BuildJobPayloadModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: str
    job_type: BuildJobType
    status: BuildJobStatus
    created_at: str
    started_at: str = ""
    finished_at: str = ""
    message: str = ""
    error: str = ""
    logs: list[str] = Field(default_factory=list)
    result: Optional[BuildJobResultModel] = None


class BuildJobResponseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job: BuildJobPayloadModel


class BuildJobListResponseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    jobs: list[BuildJobPayloadModel] = Field(default_factory=list)


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


class RouteStageSnapshotResponseModel(BaseModel):
    model_config = ConfigDict(extra="allow")

    latency_ms: float = 0.0
    doc_count: int = 0
    sources: dict[str, int] = Field(default_factory=dict)


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


class RetrievalOutcomeResponseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = ""
    strategy: str = ""
    doc_count: int = 0
    evidence_documents: list[EvidenceDocumentResponseModel] = Field(default_factory=list)
    route_trace: RouteSnapshotResponseModel = Field(default_factory=RouteSnapshotResponseModel)
    degradation_summary: JsonObject = Field(default_factory=dict)
    metadata: JsonObject = Field(default_factory=dict)


class QueryUnderstandingSnapshotResponseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = ""
    query_plan: JsonObject = Field(default_factory=dict)
    analysis: QueryAnalysisResponseModel = Field(default_factory=QueryAnalysisResponseModel)
    constraints: JsonObject = Field(default_factory=dict)
    semantic_profile: JsonObject = Field(default_factory=dict)
    metadata: JsonObject = Field(default_factory=dict)


class RouteResolutionResponseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    understanding: QueryUnderstandingSnapshotResponseModel = Field(
        default_factory=QueryUnderstandingSnapshotResponseModel
    )
    retrieval: RetrievalOutcomeResponseModel = Field(default_factory=RetrievalOutcomeResponseModel)
    metadata: JsonObject = Field(default_factory=dict)


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


class GraphTraceEventSnapshotResponseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = ""
    status: str = "ok"
    latency_ms: float = 0.0
    details: JsonObject = Field(default_factory=dict)


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


class ModelSuiteSnapshotResponseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    llm: str = ""
    embedding: str = ""
    rerank: str = ""


class RetrievalTraceSnapshotResponseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    doc_count: int = 0
    evidence: list[JsonObject] = Field(default_factory=list)
    route_trace: RouteSnapshotResponseModel = Field(default_factory=RouteSnapshotResponseModel)
    graph_trace: GraphRetrievalSnapshotResponseModel = Field(
        default_factory=GraphRetrievalSnapshotResponseModel
    )
    failure_reasons: list[str] = Field(default_factory=list)


class AnswerTraceSnapshotResponseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chars: int = 0
    preview: str = ""


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


class AnswerDiagnosticsModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    analysis: QueryAnalysisResponseModel = Field(default_factory=QueryAnalysisResponseModel)
    diagnostics: QueryDiagnosticsResponseModel = Field(
        default_factory=QueryDiagnosticsResponseModel
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


class AnswerPayloadModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: AnswerSummaryModel
    grounding: AnswerGroundingModel
    diagnostics: AnswerDiagnosticsModel
    traces: AnswerTracesModel

    @classmethod
    def from_payload(cls, payload: Mapping[str, object]) -> "AnswerPayloadModel":
        return cls.model_validate(dict(payload or {}))


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


class AnswerStreamErrorDataModel(BaseModel):
    model_config = ConfigDict(extra="allow")

    message: str
    error_type: str
    diagnostics: Optional[JsonObject] = None


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
        | AnswerStreamErrorDataModel
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
    def result(cls, response: Mapping[str, object]) -> "AnswerStreamEventModel":
        return cls(
            event=AnswerStreamEventType.result,
            data=AnswerStreamResultDataModel(response=AnswerPayloadModel.from_payload(response)),
        )

    @classmethod
    def error(
        cls,
        *,
        message: str,
        error_type: str,
        diagnostics: Optional[JsonObject] = None,
    ) -> "AnswerStreamEventModel":
        return cls(
            event=AnswerStreamEventType.error,
            data=AnswerStreamErrorDataModel(
                message=str(message),
                error_type=str(error_type),
                diagnostics=(dict(diagnostics) if diagnostics is not None else None),
            ),
        )

    @classmethod
    def done(cls) -> "AnswerStreamEventModel":
        return cls(
            event=AnswerStreamEventType.done,
            data=AnswerStreamDoneDataModel(ok=True),
        )

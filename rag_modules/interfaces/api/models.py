"""Pydantic models for the FastAPI surface."""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

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
    diagnostics: Optional[Dict[str, Any]] = None
    stats: Optional[Dict[str, Any]] = None


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
    build_metadata: Dict[str, Any] = Field(default_factory=dict)
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
    trace_stats: Dict[str, Any] = Field(default_factory=dict)
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
    trace_stats: Dict[str, Any] = Field(default_factory=dict)
    retrieval_runtime_profile: Dict[str, Any] = Field(default_factory=dict)
    artifact_manifest: ArtifactManifestResponseModel = Field(default_factory=ArtifactManifestResponseModel)
    data_stats: Dict[str, Any] = Field(default_factory=dict)
    index_stats: Dict[str, Any] = Field(default_factory=dict)
    route_stats: RouteStatsResponseModel = Field(default_factory=RouteStatsResponseModel)


class StatsResponseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stats: SystemStatsPayloadModel


class BuildJobResultModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str = ""
    diagnostics: Optional[Dict[str, Any]] = None
    stats: Optional[Dict[str, Any]] = None


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
    error: str = ""


class AnswerGroundingModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    retrieval_outcome: Dict[str, Any] = Field(default_factory=dict)
    answer_context: Dict[str, Any] = Field(default_factory=dict)
    route_resolution: Dict[str, Any] = Field(default_factory=dict)
    evidence_documents: list[Dict[str, Any]] = Field(default_factory=list)


class AnswerDiagnosticsModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    analysis: Dict[str, Any] = Field(default_factory=dict)
    diagnostics: Dict[str, Any] = Field(default_factory=dict)


class AnswerTracesModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    route_trace: Dict[str, Any] = Field(default_factory=dict)
    graph_trace: Dict[str, Any] = Field(default_factory=dict)
    generation_trace: Dict[str, Any] = Field(default_factory=dict)
    trace_event: Dict[str, Any] = Field(default_factory=dict)


class AnswerPayloadModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: AnswerSummaryModel
    grounding: AnswerGroundingModel
    diagnostics: AnswerDiagnosticsModel
    traces: AnswerTracesModel

    @classmethod
    def from_payload(cls, payload: Dict[str, Any]) -> "AnswerPayloadModel":
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
    diagnostics: Optional[Dict[str, Any]] = None


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
    def result(cls, response: Dict[str, Any]) -> "AnswerStreamEventModel":
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
        diagnostics: Optional[Dict[str, Any]] = None,
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

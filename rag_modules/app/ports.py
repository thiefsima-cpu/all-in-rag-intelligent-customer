"""Ports consumed by application orchestration."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import TYPE_CHECKING, Protocol

from ..contracts import EvidenceDocument, RequestControl, RetrievalRequest
from ..contracts.runtime import (
    AnswerContext,
    GenerationSnapshot,
    GraphRetrievalSnapshot,
    QueryTraceEvent,
    RetrievalOutcome,
    RouteSnapshot,
    RuntimeErrorDetail,
)
from ..kernel.artifacts import ArtifactManifest
from ..kernel.documents import TextDocument
from ..kernel.json_types import JsonObject, JsonValue
from ..routing.ports import GraphRAGRetrievalPort, HybridRetrievalPort
from .diagnostics import StartupDiagnostics, SystemStatsDiagnostics

if TYPE_CHECKING:
    from ..build_pipeline.graph_preparation.models import GraphLoadCounts, GraphNode
    from ..build_pipeline.graph_preparation.statistics import GraphPreparationStats
    from .runtime_view import SystemRuntime
    from .services.answer_models import QuestionAnswerResponse, QuestionAnswerResult

ProgressCallback = Callable[[str], None] | None
MessageCallback = Callable[[str], None] | None
ChunkCallback = Callable[[str], None] | None


class Neo4jDriverPort(Protocol):
    """Neo4j driver behavior consumed by app lifecycle orchestration."""

    def session(self, **kwargs: object) -> object: ...

    def close(self) -> None: ...


class Neo4jManagerPort(Protocol):
    """Neo4j manager behavior consumed by app lifecycle orchestration."""

    @property
    def driver(self) -> Neo4jDriverPort: ...

    def session(self, **kwargs: object) -> object: ...

    def close(self) -> None: ...


class GraphDataModulePort(Protocol):
    """Graph data behavior consumed by app composition and diagnostics."""

    documents: list[TextDocument]
    chunks: list[TextDocument]
    recipes: list[GraphNode]
    ingredients: list[GraphNode]
    cooking_steps: list[GraphNode]

    def load_graph_data(self) -> GraphLoadCounts | JsonObject: ...

    def build_recipe_documents(self) -> list[TextDocument]: ...

    def chunk_documents(
        self,
        chunk_size: int = 500,
        chunk_overlap: int = 50,
    ) -> list[TextDocument]: ...

    def get_statistics(self) -> GraphPreparationStats | JsonObject: ...

    def close(self) -> None: ...


class VectorIndexModulePort(Protocol):
    """Vector index behavior consumed by app composition and diagnostics."""

    collection_name: str

    def has_collection(self, collection_name: str | None = None) -> bool: ...

    def load_collection(self, collection_name: str | None = None) -> bool: ...

    def build_vector_index(
        self,
        chunks: list[TextDocument],
        *,
        collection_name: str | None = None,
    ) -> bool: ...

    def similarity_search(self, request: RetrievalRequest) -> list[JsonObject]: ...

    def get_collection_stats(self, collection_name: str | None = None) -> JsonObject: ...

    def delete_collection(self, collection_name: str | None = None) -> bool: ...

    def close(self) -> None: ...


class QueryTracerPort(Protocol):
    """Query trace behavior consumed by app workflow and lifecycle orchestration."""

    def record(
        self,
        query: str,
        analysis: object,
        documents: list[EvidenceDocument] | RetrievalOutcome | AnswerContext,
        latency_ms: float,
        answer: str | None = None,
        error: RuntimeErrorDetail | Mapping[str, JsonValue] | None = None,
        route_trace: Mapping[str, JsonValue] | RouteSnapshot | None = None,
        graph_trace: Mapping[str, JsonValue] | GraphRetrievalSnapshot | None = None,
        generation_trace: Mapping[str, JsonValue] | GenerationSnapshot | None = None,
    ) -> QueryTraceEvent: ...

    def stats(self) -> JsonObject: ...

    def close(self) -> None: ...


class CloseablePort(Protocol):
    """Generic closeable resource consumed by lifecycle orchestration."""

    def close(self) -> object: ...


class RuntimeDiagnosticsServicePort(Protocol):
    """Runtime diagnostics behavior consumed by app composition."""

    def collect_system_stats(
        self,
        *,
        runtime: "SystemRuntime",
        build_initialized: bool,
        serving_initialized: bool,
    ) -> SystemStatsDiagnostics: ...

    def collect_startup_diagnostics(
        self,
        *,
        mode: str,
        runtime: "SystemRuntime",
        build_initialized: bool,
        serving_initialized: bool,
    ) -> StartupDiagnostics: ...


class RuntimeShutdownServicePort(Protocol):
    """Runtime shutdown behavior consumed by app composition."""

    def close(self, *, runtime: "SystemRuntime") -> None: ...


class KnowledgeBaseServicePort(Protocol):
    """Knowledge-base lifecycle behavior consumed by app composition."""

    @property
    def artifacts_ready(self) -> bool: ...

    @property
    def system_ready(self) -> bool: ...

    @property
    def artifact_manifest(self) -> ArtifactManifest: ...

    @artifact_manifest.setter
    def artifact_manifest(self, manifest: ArtifactManifest) -> None: ...

    def build(
        self,
        progress: ProgressCallback = None,
        *,
        request_id: str = "",
        build_job_id: str = "",
    ) -> None: ...

    def rebuild(
        self,
        progress: ProgressCallback = None,
        *,
        request_id: str = "",
        build_job_id: str = "",
    ) -> None: ...

    def show_stats(self, progress: ProgressCallback = None) -> None: ...

    def close(self) -> None: ...


class ServingHybridRetrievalPort(HybridRetrievalPort, Protocol):
    """Hybrid retrieval behavior consumed by serving lifecycle preparation."""

    def initialize(self, chunks: list[TextDocument]) -> None: ...

    def close(self) -> None: ...


class ServingGraphRAGRetrievalPort(GraphRAGRetrievalPort, Protocol):
    """Graph retrieval behavior consumed by serving lifecycle preparation."""

    def initialize(self) -> None: ...

    def close(self) -> None: ...


class AnswerWorkflowPort(Protocol):
    """Question-answer workflow behavior consumed by app composition."""

    def answer_question(
        self,
        question: str,
        stream: bool = False,
        explain_routing: bool = False,
        message_callback: MessageCallback = None,
        chunk_callback: ChunkCallback = None,
        control: RequestControl | None = None,
    ) -> QuestionAnswerResult: ...

    def answer_question_response(
        self,
        question: str,
        stream: bool = False,
        explain_routing: bool = False,
        message_callback: MessageCallback = None,
        chunk_callback: ChunkCallback = None,
        control: RequestControl | None = None,
    ) -> QuestionAnswerResponse: ...


__all__ = [
    "CloseablePort",
    "GraphDataModulePort",
    "AnswerWorkflowPort",
    "ChunkCallback",
    "KnowledgeBaseServicePort",
    "MessageCallback",
    "Neo4jDriverPort",
    "Neo4jManagerPort",
    "ProgressCallback",
    "QueryTracerPort",
    "RuntimeDiagnosticsServicePort",
    "RuntimeShutdownServicePort",
    "ServingGraphRAGRetrievalPort",
    "ServingHybridRetrievalPort",
    "VectorIndexModulePort",
]

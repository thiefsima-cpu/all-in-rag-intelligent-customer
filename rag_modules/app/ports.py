"""Ports consumed by application orchestration."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from ..application.ports import (
    AnswerWorkflowPort,
    ChunkCallback,
    CloseablePort,
    KnowledgeBaseServicePort,
    MessageCallback,
    ProgressCallback,
    QueryTracerPort,
)
from ..contracts import RetrievalRequest
from ..kernel.documents import TextDocument
from ..kernel.json_types import JsonObject
from ..routing.ports import GraphRAGRetrievalPort, HybridRetrievalPort
from .diagnostics import StartupDiagnostics, SystemStatsDiagnostics

if TYPE_CHECKING:
    from ..contracts.graph_preparation import GraphLoadCounts, GraphNode, GraphPreparationStats
    from .runtime_view import SystemRuntime


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

    def build_documents(self) -> list[TextDocument]: ...

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


class ServingHybridRetrievalPort(HybridRetrievalPort, Protocol):
    """Hybrid retrieval behavior consumed by serving lifecycle preparation."""

    def initialize(self, chunks: list[TextDocument]) -> None: ...

    def close(self) -> None: ...


class ServingGraphRAGRetrievalPort(GraphRAGRetrievalPort, Protocol):
    """Graph retrieval behavior consumed by serving lifecycle preparation."""

    def initialize(self) -> None: ...

    def close(self) -> None: ...


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

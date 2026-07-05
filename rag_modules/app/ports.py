"""Ports consumed by application orchestration."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, Protocol

from ..contracts import EvidenceDocument, RetrievalRequest
from ..contracts.runtime import (
    AnswerContext,
    GenerationSnapshot,
    GraphRetrievalSnapshot,
    QueryTraceEvent,
    RetrievalOutcome,
    RouteSnapshot,
    RuntimeErrorDetail,
)
from ..kernel.documents import TextDocument
from ..kernel.json_types import JsonObject, JsonValue

if TYPE_CHECKING:
    from ..build_pipeline.graph_preparation.models import GraphLoadCounts
    from ..build_pipeline.graph_preparation.statistics import GraphPreparationStats


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

    def close(self) -> Any: ...


__all__ = [
    "CloseablePort",
    "GraphDataModulePort",
    "Neo4jDriverPort",
    "Neo4jManagerPort",
    "QueryTracerPort",
    "VectorIndexModulePort",
]

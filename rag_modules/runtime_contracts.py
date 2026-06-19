"""Structural runtime collaborator contracts shared below app assembly."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from .retrieval.contracts import EvidenceDocument, RetrievalRequest
    from .runtime import (
        AnswerContext,
        GenerationSnapshot,
        GraphRetrievalSnapshot,
        QueryTraceEvent,
        RetrievalOutcome,
        RouteSnapshot,
    )
    from .text_document import TextDocument


class Neo4jSessionPort(Protocol):
    """Neo4j session behavior used by retrieval adapters."""

    def __enter__(self) -> Neo4jSessionPort: ...

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None: ...

    def run(self, query: str, parameters: object | None = None, **kwargs: object) -> object: ...


class Neo4jDriverPort(Protocol):
    """Neo4j driver behavior used by retrieval adapters."""

    def session(self, **kwargs: object) -> Neo4jSessionPort: ...


class Neo4jManagerPort(Protocol):
    """Neo4j manager behavior used by runtime assembly and shutdown."""

    @property
    def driver(self) -> Neo4jDriverPort: ...

    def session(self, **kwargs: object) -> object: ...

    def close(self) -> None: ...


class GraphDataModulePort(Protocol):
    """Graph data loader and document materializer behavior."""

    documents: list[TextDocument]
    chunks: list[TextDocument]

    def load_graph_data(self) -> dict[str, object]: ...

    def build_recipe_documents(self) -> list[TextDocument]: ...

    def chunk_documents(
        self,
        chunk_size: int = 500,
        chunk_overlap: int = 50,
    ) -> list[TextDocument]: ...

    def get_statistics(self) -> dict[str, object]: ...

    def close(self) -> None: ...


class VectorIndexModulePort(Protocol):
    """Vector index behavior used by build, serving, and hybrid retrieval."""

    collection_name: str

    def has_collection(self, collection_name: str | None = None) -> bool: ...

    def load_collection(self, collection_name: str | None = None) -> bool: ...

    def build_vector_index(
        self,
        chunks: list[TextDocument],
        *,
        collection_name: str | None = None,
    ) -> bool: ...

    def similarity_search(
        self,
        query: str,
        k: int = 5,
        filters: dict[str, object] | None = None,
    ) -> list[dict[str, object]]: ...

    def get_collection_stats(self, collection_name: str | None = None) -> dict[str, object]: ...

    def delete_collection(self, collection_name: str | None = None) -> bool: ...

    def close(self) -> None: ...


class QueryTracerPort(Protocol):
    """Query trace behavior consumed by answer workflow and runtime shutdown."""

    def record(
        self,
        query: str,
        analysis: object,
        documents: list[EvidenceDocument] | RetrievalOutcome | AnswerContext,
        latency_ms: float,
        answer: str | None = None,
        error: str | None = None,
        route_trace: dict[str, object] | RouteSnapshot | None = None,
        graph_trace: dict[str, object] | GraphRetrievalSnapshot | None = None,
        generation_trace: dict[str, object] | GenerationSnapshot | None = None,
    ) -> QueryTraceEvent: ...

    def stats(self) -> dict[str, object]: ...

    def close(self) -> None: ...


class HybridCandidateRuntimePort(Protocol):
    """Candidate-source runtime behavior for hybrid retrieval."""

    def dual_level_candidates(self, request: RetrievalRequest) -> list[EvidenceDocument]: ...

    def vector_candidates(self, query: str, *, top_k: int) -> list[EvidenceDocument]: ...

    def bm25_candidates(self, query: str, *, top_k: int) -> list[EvidenceDocument]: ...


__all__ = [
    "GraphDataModulePort",
    "HybridCandidateRuntimePort",
    "Neo4jDriverPort",
    "Neo4jManagerPort",
    "Neo4jSessionPort",
    "QueryTracerPort",
    "VectorIndexModulePort",
]

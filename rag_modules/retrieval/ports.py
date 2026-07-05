"""Ports consumed by retrieval services."""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Any, Protocol

from ..contracts import EvidenceDocument, RequestControl, RetrievalRequest
from ..kernel.documents import TextDocument
from ..kernel.json_types import JsonObject

if TYPE_CHECKING:
    from ..build_pipeline.graph_preparation.models import GraphLoadCounts
    from ..build_pipeline.graph_preparation.statistics import GraphPreparationStats


class Neo4jSessionPort(Protocol):
    """Neo4j session behavior consumed by retrieval adapters."""

    def __enter__(self) -> Neo4jSessionPort: ...

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None: ...

    def run(self, query: str, parameters: object | None = None, **kwargs: object) -> Any: ...

    def execute_read(self, transaction_function: Any, *args: Any, **kwargs: Any) -> Any: ...

    def execute_write(self, transaction_function: Any, *args: Any, **kwargs: Any) -> Any: ...


class Neo4jDriverPort(Protocol):
    """Neo4j driver behavior consumed by retrieval adapters."""

    def session(self, **kwargs: object) -> Neo4jSessionPort: ...

    def close(self) -> None: ...


class Neo4jManagerPort(Protocol):
    """Neo4j manager behavior consumed by retrieval services."""

    @property
    def driver(self) -> Neo4jDriverPort: ...

    def session(self, **kwargs: object) -> object: ...

    def close(self) -> None: ...


class VectorIndexModulePort(Protocol):
    """Vector index behavior consumed by retrieval services."""

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


class GraphDataModulePort(Protocol):
    """Graph data behavior consumed by retrieval index services."""

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


class HybridCandidateRuntimePort(Protocol):
    """Candidate-source runtime behavior consumed by hybrid retrieval."""

    def dual_level_candidates(self, request: RetrievalRequest) -> list[EvidenceDocument]: ...

    def vector_candidates(self, request: RetrievalRequest) -> list[EvidenceDocument]: ...

    def bm25_candidates(self, request: RetrievalRequest) -> list[EvidenceDocument]: ...


class RerankClientPort(Protocol):
    """Provider-neutral rerank behavior consumed by retrieval post-processing."""

    def rerank(
        self,
        query: str,
        documents: Sequence[str],
        top_n: int,
        *,
        control: RequestControl | None = None,
        timeout_seconds: float | None = None,
    ) -> list[int]: ...


__all__ = [
    "GraphDataModulePort",
    "HybridCandidateRuntimePort",
    "Neo4jDriverPort",
    "Neo4jManagerPort",
    "Neo4jSessionPort",
    "RerankClientPort",
    "VectorIndexModulePort",
]

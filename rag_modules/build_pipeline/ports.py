"""Ports consumed by build-pipeline workflow services."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import TYPE_CHECKING, Protocol

from ..contracts import RetrievalRequest
from ..kernel.documents import TextDocument
from ..kernel.json_types import JsonObject

if TYPE_CHECKING:
    from ..contracts.graph_preparation import GraphLoadCounts, GraphPreparationStats


class Neo4jRecordPort(Protocol):
    """Neo4j record behavior consumed by build-pipeline loaders."""

    def __getitem__(self, key: str) -> object: ...

    def get(self, key: str, default: object | None = None) -> object: ...


class Neo4jResultPort(Protocol):
    """Neo4j result behavior consumed by build-pipeline loaders."""

    def __iter__(self) -> Iterator[Neo4jRecordPort]: ...

    def single(self) -> Neo4jRecordPort | None: ...


class Neo4jSessionPort(Protocol):
    """Neo4j session behavior consumed by build-pipeline loaders."""

    def __enter__(self) -> Neo4jSessionPort: ...

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None: ...

    def run(
        self,
        query: str,
        parameters: object | None = None,
        **kwargs: object,
    ) -> Neo4jResultPort: ...

    def execute_read(
        self,
        transaction_function: Callable[..., object],
        *args: object,
        **kwargs: object,
    ) -> object: ...

    def execute_write(
        self,
        transaction_function: Callable[..., object],
        *args: object,
        **kwargs: object,
    ) -> object: ...


class Neo4jDriverPort(Protocol):
    """Neo4j driver behavior consumed by build-pipeline loaders."""

    def session(self, **kwargs: object) -> Neo4jSessionPort: ...

    def close(self) -> None: ...


class GraphDataModulePort(Protocol):
    """Graph data loader and document materializer behavior consumed by build workflow."""

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
    """Vector index behavior consumed by build workflow."""

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


__all__ = [
    "GraphDataModulePort",
    "Neo4jDriverPort",
    "Neo4jRecordPort",
    "Neo4jResultPort",
    "Neo4jSessionPort",
    "VectorIndexModulePort",
]

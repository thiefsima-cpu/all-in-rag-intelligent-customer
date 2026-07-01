"""Structural host contract shared by Milvus operation mixins."""

from __future__ import annotations

from typing import Any

from ...runtime_contracts import EmbeddingClientPort


class MilvusOperationHost:
    """Attributes and sibling operations required across Milvus mixins."""

    active_collection_name: str
    active_collection_slot: str
    api_key: str
    base_collection_name: str
    blue_green_enabled: bool
    build_collection_name: str
    circuit_breaker_failure_threshold: int
    circuit_breaker_recovery_seconds: float
    client: Any
    collection_alias: str
    collection_created: bool
    collection_name: str
    dimension: int
    embedding_base_url: str
    embedding_batch_size: int
    embedding_client: EmbeddingClientPort | None
    embedding_timeout_seconds: int
    embeddings: EmbeddingClientPort
    host: str
    http_pool_connections: int
    http_pool_maxsize: int
    model_name: str
    port: int
    vector_search_ef: int
    vector_search_max_k: int

    def alias_target(self) -> str:
        raise NotImplementedError

    def create_collection(
        self,
        force_recreate: bool = False,
        *,
        collection_name: str | None = None,
    ) -> bool:
        raise NotImplementedError

    def create_index(self, *, collection_name: str | None = None) -> bool:
        raise NotImplementedError

    def delete_collection(self, collection_name: str | None = None) -> bool:
        raise NotImplementedError

    def physical_collection_name(self, slot: str) -> str:
        raise NotImplementedError


__all__ = ["MilvusOperationHost"]

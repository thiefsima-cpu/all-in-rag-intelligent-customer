"""Adapter assembly boundary for hybrid retrieval runtime."""

from __future__ import annotations

from typing import Protocol

from ..app.runtime_contracts import VectorIndexModulePort
from .adapters import GraphKVRetriever, VectorRetriever
from .adapters.neo4j_fallback_retriever import Neo4jFallbackRetriever
from .dual_level_evidence_service import DualLevelEvidenceService
from .dual_level_retriever import DualLevelRetriever
from .keyword_service import QueryKeywordExtractor


class HybridRuntimeAdapterFactory(Protocol):
    """Build runtime-owned adapter instances for hybrid retrieval."""

    def create_vector_retriever(
        self,
        *,
        milvus_module: VectorIndexModulePort,
        driver: object | None,
        database: str,
    ) -> VectorRetriever: ...

    def create_dual_level_retriever(
        self,
        *,
        graph_indexing: object,
        graph_kv_retriever: GraphKVRetriever,
        keyword_extractor: QueryKeywordExtractor,
        driver: object | None,
        database: str,
    ) -> DualLevelRetriever: ...


class DefaultHybridRuntimeAdapterFactory:
    """Default adapter wiring for vector and dual-level retrieval."""

    @staticmethod
    def create_vector_retriever(
        *,
        milvus_module: VectorIndexModulePort,
        driver: object | None,
        database: str,
    ) -> VectorRetriever:
        return VectorRetriever(
            milvus_module,
            driver=driver,
            database=database,
        )

    @staticmethod
    def create_dual_level_retriever(
        *,
        graph_indexing: object,
        graph_kv_retriever: GraphKVRetriever,
        keyword_extractor: QueryKeywordExtractor,
        driver: object | None,
        database: str,
    ) -> DualLevelRetriever:
        return DualLevelRetriever(
            graph_indexing=graph_indexing,
            graph_kv_retriever=graph_kv_retriever,
            keyword_extractor=keyword_extractor,
            evidence_service=DualLevelEvidenceService(
                graph_indexing=graph_indexing,
            ),
            fallback_retriever=Neo4jFallbackRetriever(
                driver=driver,
                database=database,
            ),
            driver=driver,
            database=database,
        )

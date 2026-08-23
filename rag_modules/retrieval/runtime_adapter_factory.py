"""Adapter assembly boundary for hybrid retrieval runtime."""

from __future__ import annotations

from typing import Protocol

from ..domains import DEFAULT_DOMAIN_NAME, get_domain_pack
from .adapters import GraphKVRetriever, VectorRetriever
from .adapters.neo4j_fallback_retriever import Neo4jFallbackRetriever
from .dual_level_evidence_service import DualLevelEvidenceService
from .dual_level_retriever import DualLevelRetriever
from .keyword_service import QueryKeywordExtractor
from .ports import Neo4jDriverPort, VectorIndexModulePort


class HybridRuntimeAdapterFactory(Protocol):
    """Build runtime-owned adapter instances for hybrid retrieval."""

    def create_vector_retriever(
        self,
        *,
        milvus_module: VectorIndexModulePort,
        driver: Neo4jDriverPort | None,
        database: str,
    ) -> VectorRetriever: ...

    def create_dual_level_retriever(
        self,
        *,
        graph_indexing: object,
        graph_kv_retriever: GraphKVRetriever,
        keyword_extractor: QueryKeywordExtractor,
        driver: Neo4jDriverPort | None,
        database: str,
    ) -> DualLevelRetriever: ...


class DefaultHybridRuntimeAdapterFactory:
    """Default adapter wiring for vector and dual-level retrieval."""

    @staticmethod
    def create_vector_retriever(
        *,
        milvus_module: VectorIndexModulePort,
        driver: Neo4jDriverPort | None,
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
        driver: Neo4jDriverPort | None,
        database: str,
    ) -> DualLevelRetriever:
        config = getattr(graph_indexing, "config", None)
        domain = getattr(config, "domain", None)
        domain_name = str(getattr(domain, "name", DEFAULT_DOMAIN_NAME) or DEFAULT_DOMAIN_NAME)
        domain_pack = get_domain_pack(domain_name)
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
                domain_name=domain_name,
                allowed_labels=domain_pack.ontology.node_labels,
                lookup_fields=domain_pack.ontology.entity_lookup_fields,
                allow_domainless_graph_records=domain_pack.allow_domainless_graph_records,
            ),
            driver=driver,
            database=database,
        )

"""Component assembly for the hybrid retrieval facade."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Optional

from ..configuration.models import GraphRAGConfig
from ..graph_index import GraphIndexingModule
from .adapters import BM25Retriever, ConstraintRetriever, GraphKVRetriever
from .cache import RetrievalCacheStore
from .candidate_sources import DefaultHybridCandidateSourceFactory
from .fusion import FusionRanker
from .hybrid_driver_service import HybridDriverService
from .hybrid_index_service import HybridIndexService
from .hybrid_parent_document_service import HybridParentDocumentService
from .hybrid_runtime import HybridRetrievalRuntime
from .hybrid_search_service import HybridSearchService
from .keyword_service import QueryKeywordExtractor
from .parent_doc_enricher import ParentDocumentEnricher
from .ports import (
    GraphDataModulePort,
    Neo4jManagerPort,
    VectorIndexModulePort,
)
from .runtime_adapter_factory import DefaultHybridRuntimeAdapterFactory, HybridRuntimeAdapterFactory
from .runtime_profile import RetrievalRuntimeProfile


@dataclass
class HybridRetrievalComponents:
    """Collaborators used directly by the hybrid retrieval service."""

    keyword_extractor: QueryKeywordExtractor
    runtime: HybridRetrievalRuntime
    search_service: HybridSearchService


class DefaultHybridRetrievalComponentFactory:
    """Default wiring for the hybrid retrieval runtime stack."""

    def __init__(
        self,
        *,
        circuit_state_recorder: Callable[[str, str], None] | None = None,
    ) -> None:
        self._circuit_state_recorder = circuit_state_recorder

    def _build_search_service(
        self,
        *,
        config: GraphRAGConfig,
        retrieval_profile: RetrievalRuntimeProfile,
        runtime: HybridRetrievalRuntime,
        fusion_ranker: FusionRanker,
    ) -> HybridSearchService:
        constraint_retriever = ConstraintRetriever(runtime.get_recipe_matcher)
        return HybridSearchService(
            config=config,
            retrieval_profile=retrieval_profile,
            runtime=runtime,
            fusion_ranker=fusion_ranker,
            constraint_retriever=constraint_retriever,
            candidate_source_factory=DefaultHybridCandidateSourceFactory(),
            circuit_state_recorder=self._circuit_state_recorder,
        )

    def build(
        self,
        *,
        config: GraphRAGConfig,
        milvus_module: VectorIndexModulePort,
        data_module: GraphDataModulePort,
        llm_client: object,
        neo4j_manager: Neo4jManagerPort | None,
        retrieval_profile: RetrievalRuntimeProfile,
        database: str,
        rrf_k: int,
        adapter_factory: Optional[HybridRuntimeAdapterFactory] = None,
    ) -> HybridRetrievalComponents:
        graph_indexing = GraphIndexingModule(config, llm_client)
        fusion_ranker = FusionRanker(rrf_k=rrf_k)
        cache_store = RetrievalCacheStore(config)
        parent_enricher = ParentDocumentEnricher(config)
        bm25_retriever = BM25Retriever()
        graph_kv_retriever = GraphKVRetriever(graph_indexing)
        keyword_extractor = QueryKeywordExtractor(retrieval_profile.semantics)
        index_service = HybridIndexService(
            config=config,
            data_module=data_module,
            graph_indexing=graph_indexing,
            cache_store=cache_store,
            bm25_retriever=bm25_retriever,
            parent_enricher=parent_enricher,
        )
        driver_service = HybridDriverService(
            storage=config.storage,
            neo4j_manager=neo4j_manager,
        )
        parent_document_service = HybridParentDocumentService(
            index_service=index_service,
            parent_enricher=parent_enricher,
        )
        runtime = HybridRetrievalRuntime(
            config=config,
            milvus_module=milvus_module,
            neo4j_manager=neo4j_manager,
            database=database,
            graph_indexing=graph_indexing,
            graph_kv_retriever=graph_kv_retriever,
            keyword_extractor=keyword_extractor,
            index_service=index_service,
            bm25_retriever=bm25_retriever,
            parent_enricher=parent_enricher,
            adapter_factory=adapter_factory or DefaultHybridRuntimeAdapterFactory(),
            driver_service=driver_service,
            parent_document_service=parent_document_service,
        )
        search_service = self._build_search_service(
            config=config,
            retrieval_profile=retrieval_profile,
            runtime=runtime,
            fusion_ranker=fusion_ranker,
        )
        return HybridRetrievalComponents(
            keyword_extractor=keyword_extractor,
            runtime=runtime,
            search_service=search_service,
        )

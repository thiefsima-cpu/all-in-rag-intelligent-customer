"""Component assembly for the hybrid retrieval facade."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Protocol

from ..configuration.models import GraphRAGConfig
from ..fusion import FusionRanker
from ..graph_index import GraphIndexingModule
from ..parent_doc_enricher import ParentDocumentEnricher
from ..retrieval_cache import RetrievalCacheStore
from ..runtime_contracts import (
    GraphDataModulePort,
    Neo4jManagerPort,
    VectorIndexModulePort,
)
from .adapters import BM25Retriever, ConstraintRetriever, GraphKVRetriever, tokenize_chinese
from .candidate_sources import DefaultHybridCandidateSourceFactory
from .hybrid_driver_service import HybridDriverService
from .hybrid_executor import HybridRetrievalExecutor
from .hybrid_index_service import HybridIndexService
from .hybrid_parent_document_service import HybridParentDocumentService
from .hybrid_runtime import HybridRetrievalRuntime
from .hybrid_search_service import HybridSearchService
from .keyword_service import QueryKeywordExtractor
from .runtime_adapter_factory import DefaultHybridRuntimeAdapterFactory, HybridRuntimeAdapterFactory
from .runtime_profile import RetrievalRuntimeProfile


@dataclass
class HybridRetrievalComponents:
    """Concrete collaborators used by the hybrid retrieval facade."""

    graph_indexing: GraphIndexingModule
    fusion_ranker: FusionRanker
    cache_store: RetrievalCacheStore
    parent_enricher: ParentDocumentEnricher
    bm25_retriever: BM25Retriever
    graph_kv_retriever: GraphKVRetriever
    keyword_extractor: QueryKeywordExtractor
    index_service: HybridIndexService
    runtime: HybridRetrievalRuntime
    constraint_retriever: ConstraintRetriever
    search_service: HybridSearchService
    executor: HybridRetrievalExecutor


class HybridRetrievalComponentFactory(Protocol):
    """Assembly boundary for hybrid retrieval collaborators."""

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
    ) -> HybridRetrievalComponents: ...


class DefaultHybridRetrievalComponentFactory:
    """Default wiring for the hybrid retrieval runtime stack."""

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
        constraint_retriever = ConstraintRetriever(runtime.get_recipe_matcher)
        search_service = HybridSearchService(
            config=config,
            retrieval_profile=retrieval_profile,
            runtime=runtime,
            fusion_ranker=fusion_ranker,
            constraint_retriever=constraint_retriever,
            candidate_source_factory=DefaultHybridCandidateSourceFactory(),
        )
        executor = HybridRetrievalExecutor(
            runtime=runtime,
            search_service=search_service,
            keyword_extractor=keyword_extractor,
            cache_store=cache_store,
            bm25_tokenizer=tokenize_chinese,
        )
        return HybridRetrievalComponents(
            graph_indexing=graph_indexing,
            fusion_ranker=fusion_ranker,
            cache_store=cache_store,
            parent_enricher=parent_enricher,
            bm25_retriever=bm25_retriever,
            graph_kv_retriever=graph_kv_retriever,
            keyword_extractor=keyword_extractor,
            index_service=index_service,
            runtime=runtime,
            constraint_retriever=constraint_retriever,
            search_service=search_service,
            executor=executor,
        )

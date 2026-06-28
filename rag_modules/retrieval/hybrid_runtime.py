"""Runtime coordination for hybrid retrieval resources and primitive searches."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from langchain_core.documents import Document
from rank_bm25 import BM25Okapi

from ..configuration.models import GraphRAGConfig
from ..contracts import EvidenceDocument, RetrievalRequest
from ..domain.shared.query_constraints import RecipeConstraintMatcher
from ..graph_index import GraphIndexingModule
from ..parent_doc_enricher import ParentDocumentEnricher
from ..runtime_contracts import Neo4jDriverPort, Neo4jManagerPort, VectorIndexModulePort
from .adapters import BM25Retriever, GraphKVRetriever, VectorRetriever
from .dual_level_retriever import DualLevelRetriever
from .hybrid_driver_service import HybridDriverService
from .hybrid_index_service import HybridIndexArtifacts, HybridIndexService
from .hybrid_parent_document_service import HybridParentDocumentService
from .hybrid_runtime_state import HybridRetrievalState
from .keyword_service import QueryKeywordExtractor
from .runtime_adapter_factory import (
    DefaultHybridRuntimeAdapterFactory,
    HybridRuntimeAdapterFactory,
)

logger = logging.getLogger(__name__)


class HybridRetrievalRuntime:
    """Own runtime state, adapter initialization, and primitive retrieval operations."""

    def __init__(
        self,
        *,
        config: GraphRAGConfig,
        milvus_module: VectorIndexModulePort,
        neo4j_manager: Neo4jManagerPort | None,
        database: str,
        graph_indexing: GraphIndexingModule,
        graph_kv_retriever: GraphKVRetriever,
        keyword_extractor: QueryKeywordExtractor,
        index_service: HybridIndexService,
        bm25_retriever: BM25Retriever,
        parent_enricher: ParentDocumentEnricher,
        adapter_factory: Optional[HybridRuntimeAdapterFactory] = None,
        driver_service: Optional[HybridDriverService] = None,
        parent_document_service: Optional[HybridParentDocumentService] = None,
    ) -> None:
        self.config = config
        self.storage = config.storage
        self.milvus_module = milvus_module
        self.neo4j_manager = neo4j_manager
        self.database = database
        self.graph_indexing = graph_indexing
        self.graph_kv_retriever = graph_kv_retriever
        self.keyword_extractor = keyword_extractor
        self.index_service = index_service
        self.bm25_retriever = bm25_retriever
        self.adapter_factory = adapter_factory or DefaultHybridRuntimeAdapterFactory()
        self.driver_service = driver_service or HybridDriverService(
            storage=self.storage,
            neo4j_manager=neo4j_manager,
        )
        self.parent_documents = parent_document_service or HybridParentDocumentService(
            index_service=index_service,
            parent_enricher=parent_enricher,
        )
        self.state = HybridRetrievalState()

    @property
    def driver(self) -> Neo4jDriverPort | None:
        return self.state.driver

    @property
    def bm25(self) -> BM25Okapi | None:
        return self.state.bm25

    @property
    def bm25_corpus_docs(self) -> List[Document]:
        return list(self.state.bm25_corpus_docs or [])

    @property
    def graph_indexed(self) -> bool:
        return bool(self.state.graph_indexed)

    @property
    def parent_doc_map(self) -> Dict[str, Document]:
        return dict(self.state.parent_doc_map or {})

    @property
    def recipe_matcher(self) -> Optional[RecipeConstraintMatcher]:
        return self.state.recipe_matcher

    @property
    def vector_retriever(self) -> VectorRetriever | None:
        return self.state.vector_retriever

    @property
    def dual_level_service(self) -> DualLevelRetriever | None:
        return self.state.dual_level_service

    def initialize(self, chunks: List[Document]) -> None:
        logger.info("Initializing hybrid retrieval module...")
        self.driver_service.ensure_driver(self.state)
        self.state.vector_retriever = self._new_vector_retriever()
        self.state.dual_level_service = self._new_dual_level_retriever()
        artifacts = self.index_service.initialize(chunks, driver=self.driver)
        self.apply_index_artifacts(artifacts)
        logger.info(
            "Hybrid retrieval initialized: graph_indexed=%s parent_docs=%s",
            self.state.graph_indexed,
            len(self.state.parent_doc_map),
        )

    def apply_index_artifacts(self, artifacts: HybridIndexArtifacts) -> None:
        self.state.bm25 = artifacts.bm25
        self.state.bm25_corpus_docs = list(artifacts.bm25_corpus_docs or [])
        self.state.graph_indexed = bool(artifacts.graph_indexed)
        self.parent_documents.apply_parent_doc_map(
            self.state,
            artifacts.parent_doc_map,
        )
        self.state.recipe_matcher = artifacts.recipe_matcher

    def get_recipe_matcher(self) -> Optional[RecipeConstraintMatcher]:
        return self.state.recipe_matcher

    def ensure_dual_level_service(self) -> DualLevelRetriever:
        if self.state.dual_level_service is None:
            self.state.dual_level_service = self._new_dual_level_retriever()
        return self.state.dual_level_service

    def ensure_vector_retriever(self) -> VectorRetriever:
        if self.state.vector_retriever is None:
            self.state.vector_retriever = self._new_vector_retriever()
        return self.state.vector_retriever

    def restore_bm25_retriever(self, payload: Dict[str, Any]) -> None:
        if self.index_service.restore_bm25_retriever(payload):
            self._sync_bm25_state()

    def sync_bm25_state(self) -> None:
        self._sync_bm25_state()

    def _sync_bm25_state(self) -> None:
        self.state.bm25 = self.bm25_retriever.bm25
        self.state.bm25_corpus_docs = list(self.bm25_retriever.corpus_docs)

    def build_graph_index(self) -> None:
        self.index_service._build_graph_index(self.driver)
        self.state.graph_indexed = bool(self.index_service.graph_indexed)

    def build_parent_doc_map(self) -> Dict[str, Document]:
        return self.parent_documents.build_parent_doc_map(self.state)

    def attach_parent_documents(
        self,
        docs: List[Document],
        top_n: Optional[int] = None,
    ) -> List[Document]:
        return self.parent_documents.attach_documents(
            self.state,
            docs,
            top_n=top_n,
        )

    def enrich_to_parent_documents(
        self,
        docs: List[Document],
        top_n: Optional[int] = None,
    ) -> List[Document]:
        return self.parent_documents.enrich_documents(
            self.state,
            docs,
            top_n=top_n,
        )

    def enrich_to_parent_evidence_documents(
        self,
        docs: List[EvidenceDocument],
        top_n: Optional[int] = None,
    ) -> List[EvidenceDocument]:
        return self.parent_documents.enrich_evidence_documents(
            self.state,
            docs,
            top_n=top_n,
        )

    def attach_parent_evidence_documents(
        self,
        docs: List[EvidenceDocument],
        top_n: Optional[int] = None,
    ) -> List[EvidenceDocument]:
        return self.parent_documents.attach_evidence_documents(
            self.state,
            docs,
            top_n=top_n,
        )

    def entity_level_results(
        self,
        entity_keywords: List[str],
        *,
        top_k: int = 5,
    ) -> List[EvidenceDocument]:
        return self.ensure_dual_level_service().entity_level_retrieval(
            entity_keywords,
            top_k=top_k,
        )

    def topic_level_results(
        self,
        topic_keywords: List[str],
        *,
        top_k: int = 5,
    ) -> List[EvidenceDocument]:
        return self.ensure_dual_level_service().topic_level_retrieval(
            topic_keywords,
            top_k=top_k,
        )

    def dual_level_candidates(self, request: RetrievalRequest) -> List[EvidenceDocument]:
        return self.ensure_dual_level_service().search(request)

    def vector_candidates(
        self,
        query: str,
        *,
        top_k: int,
    ) -> List[EvidenceDocument]:
        return self.ensure_vector_retriever().search(
            query,
            top_k=top_k,
        )

    def bm25_candidates(
        self,
        query: str,
        *,
        top_k: int,
    ) -> List[EvidenceDocument]:
        if not self._ensure_bm25_ready():
            logger.warning("BM25 index not initialized, returning empty result set.")
            return []
        return self.bm25_retriever.search(query, top_k=top_k)

    def close(self) -> None:
        self.driver_service.close(self.state)

    def _ensure_bm25_ready(self) -> bool:
        if getattr(self.bm25_retriever, "ready", False):
            return True
        if self.state.bm25_corpus_docs:
            self.bm25_retriever.build(self.state.bm25_corpus_docs)
            self._sync_bm25_state()
        return bool(getattr(self.bm25_retriever, "ready", False))

    def _new_vector_retriever(self) -> VectorRetriever:
        return self.adapter_factory.create_vector_retriever(
            milvus_module=self.milvus_module,
            driver=self.driver,
            database=self.database,
        )

    def _new_dual_level_retriever(self) -> DualLevelRetriever:
        return self.adapter_factory.create_dual_level_retriever(
            graph_indexing=self.graph_indexing,
            graph_kv_retriever=self.graph_kv_retriever,
            keyword_extractor=self.keyword_extractor,
            driver=self.driver,
            database=self.database,
        )


__all__ = ["HybridRetrievalRuntime"]

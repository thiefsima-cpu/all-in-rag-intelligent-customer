"""Canonical hybrid retrieval service over the retrieval runtime stack."""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from ..configuration.models import GraphRAGConfig
from ..contracts import EvidenceDocument, QueryPlan, RetrievalRequest
from ..contracts.query_constraints import QueryConstraints
from ..contracts.runtime import HybridRetrievalOutcome
from ..kernel.documents import TextDocument
from ..kernel.json_types import coerce_json_object
from .evidence import RecipeConstraintMatcher
from .hybrid_components import (
    DefaultHybridRetrievalComponentFactory,
    HybridRetrievalComponents,
)
from .ports import GraphDataModulePort, Neo4jManagerPort, VectorIndexModulePort
from .runtime_adapter_factory import HybridRuntimeAdapterFactory
from .runtime_profile import RetrievalRuntimeProfile

_DEFAULT_RRF_K = 60


class HybridRetrievalService:
    """Application-facing hybrid retrieval orchestration and lifecycle."""

    def __init__(
        self,
        config: GraphRAGConfig,
        milvus_module: VectorIndexModulePort,
        data_module: GraphDataModulePort,
        llm_client: object,
        neo4j_manager: Optional[Neo4jManagerPort] = None,
        retrieval_profile: Optional[RetrievalRuntimeProfile] = None,
        component_factory: Optional[DefaultHybridRetrievalComponentFactory] = None,
        adapter_factory: Optional[HybridRuntimeAdapterFactory] = None,
    ) -> None:
        self.config = config
        self.milvus_module = milvus_module
        self.data_module = data_module
        self.llm_client = llm_client
        self.neo4j_manager = neo4j_manager
        self.retrieval_profile = retrieval_profile or RetrievalRuntimeProfile.from_config(config)
        self.database = config.storage.neo4j_database
        self.rrf_k = int(config.retrieval.rrf_k or _DEFAULT_RRF_K)
        self.component_factory = component_factory or DefaultHybridRetrievalComponentFactory()
        self._components = self.component_factory.build(
            config=config,
            milvus_module=milvus_module,
            data_module=data_module,
            llm_client=llm_client,
            neo4j_manager=neo4j_manager,
            retrieval_profile=self.retrieval_profile,
            database=self.database,
            rrf_k=self.rrf_k,
            adapter_factory=adapter_factory,
        )

    @property
    def components(self) -> HybridRetrievalComponents:
        return self._components

    @property
    def driver(self) -> object | None:
        return self._components.runtime.driver

    @property
    def bm25(self) -> object | None:
        return self._components.runtime.bm25

    @property
    def bm25_corpus_docs(self) -> List[TextDocument]:
        return self._components.runtime.bm25_corpus_docs

    @property
    def graph_indexed(self) -> bool:
        return self._components.runtime.graph_indexed

    @property
    def recipe_matcher(self) -> Optional[RecipeConstraintMatcher]:
        return self._components.runtime.recipe_matcher

    @property
    def vector_retriever(self) -> object | None:
        return self._components.runtime.vector_retriever

    @property
    def dual_level_service(self) -> object | None:
        return self._components.runtime.dual_level_service

    def initialize(self, chunks: List[TextDocument]) -> None:
        self._components.runtime.initialize(chunks)

    def _build_request(
        self,
        query: str,
        top_k: int = 5,
        constraints: Optional[QueryConstraints] = None,
        candidate_k: Optional[int] = None,
        query_plan: Optional[QueryPlan] = None,
        *,
        entity_keywords: Optional[List[str]] = None,
        topic_keywords: Optional[List[str]] = None,
        metadata: Optional[Dict[str, object]] = None,
    ) -> RetrievalRequest:
        return RetrievalRequest.from_inputs(
            query=query,
            top_k=top_k,
            candidate_k=candidate_k,
            strategy=query_plan.strategy_value if query_plan else "",
            constraints=constraints,
            query_plan=query_plan,
            entity_keywords=entity_keywords,
            topic_keywords=topic_keywords,
            metadata=coerce_json_object(metadata),
        )

    def extract_query_keywords(self, query: str) -> Tuple[List[str], List[str]]:
        return self._components.keyword_extractor.extract(query)

    def dual_level_retrieval(
        self,
        query: str,
        top_k: int = 5,
        entity_keywords: Optional[List[str]] = None,
        topic_keywords: Optional[List[str]] = None,
    ) -> List[EvidenceDocument]:
        request = self._build_request(
            query,
            top_k=top_k,
            candidate_k=top_k,
            entity_keywords=entity_keywords,
            topic_keywords=topic_keywords,
        )
        return self._components.search_service.dual_level_candidates(request)

    def vector_search_enhanced(self, query: str, top_k: int = 5) -> List[EvidenceDocument]:
        request = self._build_request(query, top_k=top_k, candidate_k=top_k)
        return self._components.search_service.vector_candidates(request)

    def bm25_search(self, query: str, top_k: int = 5) -> List[EvidenceDocument]:
        request = self._build_request(query, top_k=top_k, candidate_k=top_k)
        return self._components.search_service.bm25_candidates(request)

    def constraint_search(
        self,
        constraints: Optional[QueryConstraints],
        top_k: int = 20,
    ) -> List[EvidenceDocument]:
        request = RetrievalRequest.from_inputs(
            query="",
            top_k=top_k,
            candidate_k=top_k,
            constraints=constraints,
        )
        return self._components.search_service.constraint_candidates(request)

    def enrich_to_parent_documents(
        self,
        docs: List[TextDocument],
        top_n: Optional[int] = None,
    ) -> List[TextDocument]:
        return self._components.runtime.enrich_to_parent_documents(docs, top_n=top_n)

    def enrich_to_parent_evidence_documents(
        self,
        request: RetrievalRequest,
        docs: List[EvidenceDocument],
        top_n: Optional[int] = None,
    ) -> List[EvidenceDocument]:
        if request.control is not None:
            request.control.raise_if_cancelled()
        return self._components.runtime.enrich_to_parent_evidence_documents(docs, top_n=top_n)

    def hybrid_evidence_search(self, request: RetrievalRequest) -> HybridRetrievalOutcome:
        return self._components.search_service.hybrid_evidence_search(request)

    def hybrid_search(self, request: RetrievalRequest) -> List[EvidenceDocument]:
        return list(self.hybrid_evidence_search(request).documents)

    def close(self) -> None:
        self._components.runtime.close()


__all__ = ["HybridRetrievalService"]

"""Canonical hybrid retrieval service over the retrieval package runtime stack."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple, Union

from langchain_core.documents import Document

from ..contracts import EvidenceDocument, QueryPlan, RetrievalRequest, to_langchain_documents
from ..domain.shared.query_constraints import QueryConstraints
from ..fusion import FusionRanker
from ..runtime_contracts import Neo4jManagerPort
from .adapters import tokenize_chinese
from .evidence import RecipeConstraintMatcher
from .hybrid_components import (
    DefaultHybridRetrievalComponentFactory,
    HybridRetrievalComponentFactory,
    HybridRetrievalComponents,
)
from .hybrid_executor import HybridRetrievalExecutor
from .hybrid_index_service import HybridIndexArtifacts
from .hybrid_outcome import HybridRetrievalOutcome
from .runtime_adapter_factory import HybridRuntimeAdapterFactory
from .runtime_profile import RetrievalRuntimeProfile

_DEFAULT_RRF_K = 60


class HybridRetrievalService:
    """Application-facing service over the hybrid retrieval executor stack."""

    def __init__(
        self,
        config,
        milvus_module,
        data_module,
        llm_client,
        neo4j_manager: Optional[Neo4jManagerPort] = None,
        retrieval_profile: Optional[RetrievalRuntimeProfile] = None,
        component_factory: Optional[HybridRetrievalComponentFactory] = None,
        adapter_factory: Optional[HybridRuntimeAdapterFactory] = None,
    ):
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
        self._executor = self._components.executor

    @property
    def components(self) -> HybridRetrievalComponents:
        return self._components

    @property
    def executor(self) -> HybridRetrievalExecutor:
        return self._executor

    @property
    def driver(self):
        return self._executor.driver

    @property
    def bm25(self):
        return self._executor.bm25

    @property
    def bm25_corpus_docs(self) -> List[Document]:
        return self._executor.bm25_corpus_docs

    @property
    def graph_indexed(self) -> bool:
        return self._executor.graph_indexed

    @property
    def _parent_doc_map(self) -> Dict[str, Document]:
        return self._executor.parent_doc_map

    @property
    def recipe_matcher(self) -> Optional[RecipeConstraintMatcher]:
        return self._executor.recipe_matcher

    @property
    def vector_retriever(self):
        return self._executor.vector_retriever

    @property
    def dual_level_service(self):
        return self._executor.dual_level_service

    def initialize(self, chunks: List[Document]):
        self._executor.initialize(chunks)

    def _apply_index_artifacts(self, artifacts: HybridIndexArtifacts) -> None:
        self._executor.apply_index_artifacts(artifacts)

    def _get_recipe_matcher(self) -> Optional[RecipeConstraintMatcher]:
        return self._executor.get_recipe_matcher()

    def _ensure_dual_level_service(self):
        return self._executor.ensure_dual_level_service()

    def _build_request(
        self,
        request_or_query: Union[str, RetrievalRequest],
        top_k: int = 5,
        constraints: Optional[QueryConstraints] = None,
        candidate_k: Optional[int] = None,
        query_plan: Optional[QueryPlan] = None,
        *,
        entity_keywords: Optional[List[str]] = None,
        topic_keywords: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> RetrievalRequest:
        return self._executor.build_request(
            request_or_query,
            top_k=top_k,
            constraints=constraints,
            candidate_k=candidate_k,
            query_plan=query_plan,
            entity_keywords=entity_keywords,
            topic_keywords=topic_keywords,
            metadata=metadata,
        )

    def _cache_signature(self, chunks: List[Document]) -> str:
        return self._executor.cache_signature(chunks)

    def _cache_path(self) -> str:
        return self._executor.cache_path()

    @staticmethod
    def _tokenize_chinese(text: str) -> List[str]:
        return tokenize_chinese(text)

    def _sync_bm25_state(self) -> None:
        self._executor.sync_bm25_state()

    def _restore_bm25_retriever(self, payload: Dict[str, Any]) -> None:
        self._executor.restore_bm25_retriever(payload)

    def _build_graph_index(self):
        self._executor.build_graph_index()

    def _build_parent_doc_map(self) -> Dict[str, Document]:
        return self._executor.build_parent_doc_map()

    def extract_query_keywords(self, query: str) -> Tuple[List[str], List[str]]:
        return self._executor.extract_query_keywords(query)

    @staticmethod
    def _dedupe_terms(terms: List[str]) -> List[str]:
        return HybridRetrievalExecutor.dedupe_terms(terms)

    def dual_level_retrieval(
        self,
        query: str,
        top_k: int = 5,
        entity_keywords: Optional[List[str]] = None,
        topic_keywords: Optional[List[str]] = None,
    ) -> List[Document]:
        request = self._build_request(
            query,
            top_k=top_k,
            candidate_k=top_k,
            entity_keywords=entity_keywords,
            topic_keywords=topic_keywords,
        )
        return to_langchain_documents(self._dual_level_candidates(request))

    def _dual_level_candidates(self, request: RetrievalRequest) -> List[EvidenceDocument]:
        return self._executor.dual_level_candidates(request)

    def vector_search_enhanced(self, query: str, top_k: int = 5) -> List[Document]:
        request = self._build_request(query, top_k=top_k, candidate_k=top_k)
        return to_langchain_documents(self._vector_candidates(request))

    def _vector_candidates(self, request: RetrievalRequest) -> List[EvidenceDocument]:
        return self._executor.vector_candidates(request)

    def bm25_search(self, query: str, top_k: int = 5) -> List[Document]:
        request = self._build_request(query, top_k=top_k, candidate_k=top_k)
        return to_langchain_documents(self._bm25_candidates(request))

    def _bm25_candidates(self, request: RetrievalRequest) -> List[EvidenceDocument]:
        return self._executor.bm25_candidates(request)

    def constraint_search(
        self,
        constraints: Optional[QueryConstraints],
        top_k: int = 20,
    ) -> List[Document]:
        request = RetrievalRequest.from_inputs(
            query="",
            top_k=top_k,
            candidate_k=top_k,
            constraints=constraints,
        )
        return to_langchain_documents(self._constraint_candidates(request))

    def _constraint_candidates(self, request: RetrievalRequest) -> List[EvidenceDocument]:
        return self._executor.constraint_candidates(request)

    @staticmethod
    def _rrf_merge(
        ranked_lists: List[Tuple[str, List[EvidenceDocument]]],
        top_k: int,
        k: int = _DEFAULT_RRF_K,
    ) -> List[EvidenceDocument]:
        return FusionRanker(rrf_k=k).rrf_merge(ranked_lists=ranked_lists, top_k=top_k)

    def _attach_parent_documents(
        self,
        docs: List[Document],
        top_n: Optional[int] = None,
    ) -> List[Document]:
        return self._executor.attach_parent_documents(docs, top_n=top_n)

    def enrich_to_parent_documents(
        self,
        docs: List[Document],
        top_n: Optional[int] = None,
    ) -> List[Document]:
        return self._executor.enrich_to_parent_documents(docs, top_n=top_n)

    def enrich_to_parent_evidence_documents(
        self,
        docs: List[EvidenceDocument],
        top_n: Optional[int] = None,
    ) -> List[EvidenceDocument]:
        return self._executor.enrich_to_parent_evidence_documents(docs, top_n=top_n)

    def _attach_parent_evidence_documents(
        self,
        docs: List[EvidenceDocument],
        top_n: Optional[int] = None,
    ) -> List[EvidenceDocument]:
        return self._executor.attach_parent_evidence_documents(docs, top_n=top_n)

    def _prepare_hybrid_request(
        self,
        request_or_query: Union[str, RetrievalRequest],
        top_k: int = 5,
        constraints: Optional[QueryConstraints] = None,
        candidate_k: Optional[int] = None,
        query_plan: Optional[QueryPlan] = None,
    ) -> RetrievalRequest:
        return self._executor.prepare_hybrid_request(
            request_or_query,
            top_k=top_k,
            constraints=constraints,
            candidate_k=candidate_k,
            query_plan=query_plan,
        )

    def hybrid_evidence_search(
        self,
        request_or_query: Union[str, RetrievalRequest],
        top_k: int = 5,
        constraints: Optional[QueryConstraints] = None,
        candidate_k: Optional[int] = None,
        query_plan: Optional[QueryPlan] = None,
    ) -> HybridRetrievalOutcome:
        return self._executor.hybrid_evidence_search(
            request_or_query,
            top_k=top_k,
            constraints=constraints,
            candidate_k=candidate_k,
            query_plan=query_plan,
        )

    def hybrid_search(
        self,
        request_or_query: Union[str, RetrievalRequest],
        top_k: int = 5,
        constraints: Optional[QueryConstraints] = None,
        candidate_k: Optional[int] = None,
        query_plan: Optional[QueryPlan] = None,
    ) -> List[Document]:
        outcome = self.hybrid_evidence_search(
            request_or_query,
            top_k=top_k,
            constraints=constraints,
            candidate_k=candidate_k,
            query_plan=query_plan,
        )
        return to_langchain_documents(
            outcome.documents,
        )

    def close(self):
        self._executor.close()


__all__ = [
    "HybridRetrievalService",
]

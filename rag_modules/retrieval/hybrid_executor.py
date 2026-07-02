"""Evidence-native execution layer for hybrid retrieval."""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from ..contracts import EvidenceDocument, RetrievalRequest
from ..text_document import TextDocument
from .evidence import RecipeConstraintMatcher
from .hybrid_outcome import HybridRetrievalOutcome
from .keyword_service import QueryKeywordExtractor


class HybridRetrievalExecutor:
    """Own hybrid request shaping, execution, and retrieval resource lifecycle."""

    def __init__(
        self,
        *,
        runtime,
        search_service,
        keyword_extractor: QueryKeywordExtractor,
        cache_store,
        bm25_tokenizer,
    ) -> None:
        self.runtime = runtime
        self.search_service = search_service
        self.keyword_extractor = keyword_extractor
        self.cache_store = cache_store
        self._bm25_tokenizer = bm25_tokenizer

    @property
    def driver(self):
        return self.runtime.driver

    @property
    def bm25(self):
        return self.runtime.bm25

    @property
    def bm25_corpus_docs(self) -> List[TextDocument]:
        return self.runtime.bm25_corpus_docs

    @property
    def graph_indexed(self) -> bool:
        return self.runtime.graph_indexed

    @property
    def parent_doc_map(self) -> Dict[str, TextDocument]:
        return self.runtime.parent_doc_map

    @property
    def recipe_matcher(self) -> Optional[RecipeConstraintMatcher]:
        return self.runtime.recipe_matcher

    @property
    def vector_retriever(self):
        return self.runtime.vector_retriever

    @property
    def dual_level_service(self):
        return self.runtime.dual_level_service

    def initialize(self, chunks: List[TextDocument]) -> None:
        self.runtime.initialize(chunks)

    def apply_index_artifacts(self, artifacts) -> None:
        self.runtime.apply_index_artifacts(artifacts)

    def prepare_hybrid_request(self, request: RetrievalRequest) -> RetrievalRequest:
        return self.search_service.prepare_hybrid_request(request)

    def cache_signature(self, chunks: List[TextDocument]) -> str:
        return self.cache_store.signature(chunks)

    def cache_path(self) -> str:
        return self.cache_store.path()

    def build_graph_index(self) -> None:
        self.runtime.build_graph_index()

    def build_parent_doc_map(self) -> Dict[str, TextDocument]:
        return self.runtime.build_parent_doc_map()

    def get_recipe_matcher(self) -> Optional[RecipeConstraintMatcher]:
        return self.runtime.get_recipe_matcher()

    def ensure_dual_level_service(self):
        return self.runtime.ensure_dual_level_service()

    def extract_query_keywords(self, query: str) -> Tuple[List[str], List[str]]:
        return self.keyword_extractor.extract(query)

    @staticmethod
    def dedupe_terms(terms: List[str]) -> List[str]:
        return QueryKeywordExtractor.dedupe_terms(terms)

    def entity_level_results(
        self,
        entity_keywords: List[str],
        *,
        top_k: int = 5,
    ) -> List[EvidenceDocument]:
        return self.runtime.entity_level_results(
            entity_keywords,
            top_k=top_k,
        )

    def topic_level_results(
        self,
        topic_keywords: List[str],
        *,
        top_k: int = 5,
    ) -> List[EvidenceDocument]:
        return self.runtime.topic_level_results(
            topic_keywords,
            top_k=top_k,
        )

    def dual_level_candidates(self, request: RetrievalRequest) -> List[EvidenceDocument]:
        return self.search_service.dual_level_candidates(request)

    def vector_candidates(self, request: RetrievalRequest) -> List[EvidenceDocument]:
        return self.search_service.vector_candidates(request)

    def bm25_candidates(self, request: RetrievalRequest) -> List[EvidenceDocument]:
        return self.search_service.bm25_candidates(request)

    def constraint_candidates(self, request: RetrievalRequest) -> List[EvidenceDocument]:
        return self.search_service.constraint_candidates(request)

    def hybrid_evidence_search(self, request: RetrievalRequest) -> HybridRetrievalOutcome:
        return self.search_service.hybrid_evidence_search(request)

    def attach_parent_documents(
        self,
        docs: List[TextDocument],
        *,
        top_n: Optional[int] = None,
    ) -> List[TextDocument]:
        return self.runtime.attach_parent_documents(docs, top_n=top_n)

    def enrich_to_parent_documents(
        self,
        docs: List[TextDocument],
        *,
        top_n: Optional[int] = None,
    ) -> List[TextDocument]:
        return self.runtime.enrich_to_parent_documents(docs, top_n=top_n)

    def attach_parent_evidence_documents(
        self,
        docs: List[EvidenceDocument],
        *,
        top_n: Optional[int] = None,
    ) -> List[EvidenceDocument]:
        return self.runtime.attach_parent_evidence_documents(docs, top_n=top_n)

    def enrich_to_parent_evidence_documents(
        self,
        request: RetrievalRequest,
        docs: List[EvidenceDocument],
        *,
        top_n: Optional[int] = None,
    ) -> List[EvidenceDocument]:
        if request.control is not None:
            request.control.raise_if_cancelled()
        return self.runtime.enrich_to_parent_evidence_documents(docs, top_n=top_n)

    def restore_bm25_retriever(self, payload: Dict[str, object]) -> None:
        self.runtime.restore_bm25_retriever(payload)

    def sync_bm25_state(self) -> None:
        self.runtime.sync_bm25_state()

    def tokenize_chinese(self, text: str) -> List[str]:
        return self._bm25_tokenizer(text)

    def close(self) -> None:
        self.runtime.close()

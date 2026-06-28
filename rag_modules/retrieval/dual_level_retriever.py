"""Dual-level graph retrieval orchestrator."""

from __future__ import annotations

import logging
from typing import List, Optional

from ..contracts import EvidenceDocument, RetrievalRequest
from .adapters.neo4j_fallback_retriever import Neo4jFallbackRetriever
from .dual_level_evidence_service import DualLevelEvidenceService
from .keyword_service import QueryKeywordExtractor

logger = logging.getLogger(__name__)


class DualLevelRetriever:
    """Orchestrate entity-level and topic-level retrieval across index and fallback adapters."""

    def __init__(
        self,
        *,
        driver,
        database: str,
        graph_indexing,
        graph_kv_retriever,
        keyword_extractor: QueryKeywordExtractor,
        evidence_service: Optional[DualLevelEvidenceService] = None,
        fallback_retriever: Optional[Neo4jFallbackRetriever] = None,
    ) -> None:
        self.graph_kv_retriever = graph_kv_retriever
        self.keyword_extractor = keyword_extractor
        self.evidence_service = evidence_service or DualLevelEvidenceService(
            graph_indexing=graph_indexing
        )
        self.fallback_retriever = fallback_retriever or Neo4jFallbackRetriever(
            driver=driver,
            database=database,
        )

    def search(self, request: RetrievalRequest) -> List[EvidenceDocument]:
        logger.info("Starting dual-level retrieval: candidate_k=%s", request.effective_candidate_k)
        entity_keywords, topic_keywords = self._resolve_keywords(request)

        entity_results = self.entity_level_retrieval(
            entity_keywords,
            top_k=request.effective_candidate_k,
        )
        topic_results = self.topic_level_retrieval(
            topic_keywords,
            top_k=request.effective_candidate_k,
        )

        combined = self.evidence_service.sort_and_dedupe(
            entity_results + topic_results,
            top_k=request.effective_candidate_k,
        )
        logger.info("Dual-level retrieval complete: %s docs", len(combined))
        return combined

    def entity_level_retrieval(
        self, entity_keywords: List[str], top_k: int = 5
    ) -> List[EvidenceDocument]:
        results = self.evidence_service.enrich_entity_candidates(
            self.graph_kv_retriever.entity_search(entity_keywords, top_k=top_k),
            neighbor_lookup=self.fallback_retriever.node_neighbors,
        )
        if len(results) < top_k:
            results.extend(
                self.fallback_retriever.entity_search(entity_keywords, top_k - len(results))
            )
        return self.evidence_service.sort_and_dedupe(results, top_k=top_k)

    def topic_level_retrieval(
        self, topic_keywords: List[str], top_k: int = 5
    ) -> List[EvidenceDocument]:
        results = self.evidence_service.enrich_topic_candidates(
            self.graph_kv_retriever.topic_search(topic_keywords, top_k=top_k)
        )
        results.extend(self.evidence_service.category_topic_candidates(topic_keywords))
        if len(results) < top_k:
            results.extend(
                self.fallback_retriever.topic_search(topic_keywords, top_k - len(results))
            )
        return self.evidence_service.sort_and_dedupe(results, top_k=top_k)

    def _resolve_keywords(self, request: RetrievalRequest) -> tuple[List[str], List[str]]:
        extracted_entities: List[str] = []
        extracted_topics: List[str] = []
        if not request.planned_entity_keywords or not request.planned_topic_keywords:
            extracted_entities, extracted_topics = self.keyword_extractor.extract(request.query)
        entity_keywords = self.keyword_extractor.dedupe_terms(
            request.planned_entity_keywords or extracted_entities
        )
        topic_keywords = self.keyword_extractor.dedupe_terms(
            request.planned_topic_keywords or extracted_topics
        )
        return entity_keywords, topic_keywords

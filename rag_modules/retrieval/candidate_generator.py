"""Candidate generation for hybrid retrieval."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Sequence, Tuple

from .candidate_sources import CandidateSourceSpec, RetrievalCandidateSource
from .contracts import EvidenceDocument, RetrievalRequest

logger = logging.getLogger(__name__)


@dataclass
class CandidateSourceResult:
    """Documents produced by one retrieval candidate source."""

    spec: CandidateSourceSpec
    documents: List[EvidenceDocument] = field(default_factory=list)


@dataclass
class CandidateSet:
    """Normalized candidate documents across all configured sources."""

    source_results: List[CandidateSourceResult] = field(default_factory=list)

    @property
    def dual_docs(self) -> List[EvidenceDocument]:
        return self.documents_for("dual")

    @property
    def vector_docs(self) -> List[EvidenceDocument]:
        return self.documents_for("vector")

    @property
    def bm25_docs(self) -> List[EvidenceDocument]:
        return self.documents_for("bm25")

    @property
    def constraint_docs(self) -> List[EvidenceDocument]:
        return self.documents_for("constraints")

    @property
    def ranked_lists(self) -> List[Tuple[str, List[EvidenceDocument]]]:
        ranked: List[Tuple[str, List[EvidenceDocument]]] = []
        for result in sorted(self.source_results, key=lambda item: item.spec.rank_order):
            if result.documents:
                ranked.append((result.spec.rank_name, list(result.documents)))
        return ranked

    @property
    def stats(self) -> dict:
        return {
            result.spec.name: len(result.documents)
            for result in sorted(self.source_results, key=lambda item: item.spec.rank_order)
        }

    def documents_for(self, source_name: str) -> List[EvidenceDocument]:
        for result in self.source_results:
            if result.spec.name == source_name:
                return list(result.documents)
        return []


class RetrievalCandidateGenerator:
    """Generate hybrid retrieval candidates from configured source contracts."""

    def __init__(
        self,
        *,
        sources: Sequence[RetrievalCandidateSource],
    ):
        self.sources = tuple(sources)

    def generate(self, request: RetrievalRequest) -> CandidateSet:
        effective_request = self._calibrate_request(request)
        results: List[CandidateSourceResult] = []
        for source in self.sources:
            documents = self._normalize_source_documents(
                source.retrieve(effective_request),
                spec=source.spec,
            )
            results.append(
                CandidateSourceResult(
                    spec=source.spec,
                    documents=documents,
                )
            )
        candidate_set = CandidateSet(source_results=results)
        logger.debug("Hybrid candidate generation stats: %s", candidate_set.stats)
        return candidate_set

    @staticmethod
    def _calibrate_request(request: RetrievalRequest) -> RetrievalRequest:
        effective_request = request
        if request.query_plan:
            if not request.entity_keywords and request.planned_entity_keywords:
                effective_request = effective_request.copy_with(
                    entity_keywords=request.planned_entity_keywords,
                )
            if not request.topic_keywords and request.planned_topic_keywords:
                effective_request = effective_request.copy_with(
                    topic_keywords=request.planned_topic_keywords,
                )
            if (
                not request.effective_constraints.has_constraints()
                and request.query_plan.constraints.has_constraints()
            ):
                effective_request = effective_request.copy_with(
                    constraints=request.query_plan.constraints,
                )
        return effective_request

    @staticmethod
    def _normalize_source_documents(
        documents: List[EvidenceDocument],
        *,
        spec: CandidateSourceSpec,
    ) -> List[EvidenceDocument]:
        normalized: List[EvidenceDocument] = []
        for doc in documents or []:
            metadata: Dict[str, object] = dict(doc.metadata or {})
            metadata.setdefault("search_method", doc.search_method or spec.search_method)
            metadata.setdefault("search_type", doc.search_type or spec.search_type)
            normalized.append(
                doc.copy_with(
                    search_method=doc.search_method or spec.search_method,
                    search_type=doc.search_type or spec.search_type,
                    metadata=metadata,
                )
            )
        return normalized


__all__ = [
    "CandidateSet",
    "CandidateSourceResult",
    "RetrievalCandidateGenerator",
]

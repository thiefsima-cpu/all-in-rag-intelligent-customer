"""Search orchestration for hybrid retrieval."""

from __future__ import annotations

import logging
from typing import List, Optional, Union

from ..contracts import QueryPlan, RetrievalRequest
from ..domain.shared.query_constraints import QueryConstraints
from ..fusion import FusionRanker
from .adapters import ConstraintRetriever
from .candidate_generator import RetrievalCandidateGenerator
from .candidate_sources import (
    DefaultHybridCandidateSourceFactory,
    HybridCandidateSourceFactory,
)
from .hybrid_outcome import HybridRetrievalOutcome
from .runtime_profile import RetrievalRuntimeProfile

logger = logging.getLogger(__name__)


class HybridSearchService:
    """Own request shaping and multi-source hybrid search orchestration."""

    def __init__(
        self,
        *,
        config,
        retrieval_profile: RetrievalRuntimeProfile,
        runtime,
        fusion_ranker: FusionRanker,
        constraint_retriever: ConstraintRetriever,
        candidate_source_factory: HybridCandidateSourceFactory | None = None,
        candidate_generator: RetrievalCandidateGenerator | None = None,
    ) -> None:
        self.config = config
        self.retrieval = config.retrieval
        self.retrieval_profile = retrieval_profile
        self.runtime = runtime
        self.fusion_ranker = fusion_ranker
        self.constraint_retriever = constraint_retriever
        self.candidate_source_factory = (
            candidate_source_factory or DefaultHybridCandidateSourceFactory()
        )
        candidate_source_settings = getattr(self.retrieval_profile, "candidate_sources", None)
        self.candidate_generator = candidate_generator or RetrievalCandidateGenerator(
            sources=self.candidate_source_factory.build(
                runtime=runtime,
                constraint_retriever=constraint_retriever,
            ),
            source_failure_threshold=getattr(candidate_source_settings, "failure_threshold", 1),
            source_recovery_timeout_seconds=getattr(
                candidate_source_settings,
                "recovery_timeout_seconds",
                30.0,
            ),
            source_degradation_strategy=getattr(
                candidate_source_settings,
                "degradation_strategy",
                "continue",
            ),
        )

    def build_request(
        self,
        request_or_query: Union[str, RetrievalRequest],
        *,
        top_k: int = 5,
        constraints: Optional[QueryConstraints] = None,
        candidate_k: Optional[int] = None,
        query_plan: Optional[QueryPlan] = None,
        entity_keywords: Optional[List[str]] = None,
        topic_keywords: Optional[List[str]] = None,
        metadata: Optional[dict] = None,
    ) -> RetrievalRequest:
        if isinstance(request_or_query, RetrievalRequest):
            return request_or_query
        return RetrievalRequest.from_inputs(
            query=request_or_query,
            top_k=top_k,
            candidate_k=candidate_k,
            strategy=query_plan.strategy if query_plan else "",
            constraints=constraints,
            query_plan=query_plan,
            entity_keywords=entity_keywords,
            topic_keywords=topic_keywords,
            metadata=metadata,
        )

    def prepare_hybrid_request(
        self,
        request_or_query: Union[str, RetrievalRequest],
        *,
        top_k: int = 5,
        constraints: Optional[QueryConstraints] = None,
        candidate_k: Optional[int] = None,
        query_plan: Optional[QueryPlan] = None,
    ) -> RetrievalRequest:
        request = self.build_request(
            request_or_query,
            top_k=top_k,
            constraints=constraints,
            candidate_k=candidate_k,
            query_plan=query_plan,
        )
        effective_constraints = request.effective_constraints
        if request.candidate_k <= 0:
            constrained = bool(effective_constraints and effective_constraints.has_constraints())
            request = request.copy_with(
                candidate_k=self.retrieval_profile.candidates.hybrid_candidate_k(
                    request.top_k,
                    constrained=constrained,
                )
            )
        return request

    def hybrid_evidence_search(
        self,
        request_or_query: Union[str, RetrievalRequest],
        *,
        top_k: int = 5,
        constraints: Optional[QueryConstraints] = None,
        candidate_k: Optional[int] = None,
        query_plan: Optional[QueryPlan] = None,
    ) -> HybridRetrievalOutcome:
        request = self.prepare_hybrid_request(
            request_or_query,
            top_k=top_k,
            constraints=constraints,
            candidate_k=candidate_k,
            query_plan=query_plan,
        )
        effective_constraints = request.effective_constraints

        logger.info(
            "Starting hybrid retrieval: rrf_k=%s top_k=%s",
            self.fusion_ranker.rrf_k,
            request.top_k,
        )

        candidates = self.candidate_generator.generate(request)
        final_docs = self.fusion_ranker.rrf_merge(
            ranked_lists=candidates.ranked_lists,
            top_k=request.top_k,
        )

        if self.retrieval.enable_parent_doc_retrieval:
            final_docs = self.runtime.attach_parent_evidence_documents(
                final_docs,
                top_n=request.top_k
                if effective_constraints and effective_constraints.has_constraints()
                else None,
            )

        stats = candidates.stats
        logger.info(
            "Hybrid retrieval complete: constraints=%s dual=%s vector=%s bm25=%s final=%s",
            stats.get("constraints", 0),
            stats.get("dual", 0),
            stats.get("vector", 0),
            stats.get("bm25", 0),
            len(final_docs),
        )
        return HybridRetrievalOutcome.from_candidate_set(
            documents=final_docs,
            candidates=candidates,
        )

"""Search orchestration for hybrid retrieval."""

from __future__ import annotations

import logging
from collections.abc import Callable

from ..contracts import EvidenceDocument, RetrievalRequest
from ..contracts.runtime import HybridRetrievalOutcome
from .adapters import ConstraintRetriever
from .candidate_generator import CandidateSet, RetrievalCandidateGenerator
from .candidate_sources import (
    DefaultHybridCandidateSourceFactory,
    HybridCandidateSourceFactory,
)
from .fusion import FusionRanker
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
        circuit_state_recorder: Callable[[str, str], None] | None = None,
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
            circuit_state_recorder=circuit_state_recorder,
        )

    def prepare_hybrid_request(self, request: RetrievalRequest) -> RetrievalRequest:
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

    def _generate_candidate_set(self, request: RetrievalRequest) -> CandidateSet:
        request = self.prepare_hybrid_request(request)
        control = request.control
        if control is not None:
            control.raise_if_cancelled()
        candidates = self.candidate_generator.generate(request)
        if control is not None:
            control.raise_if_cancelled()
        return candidates

    def dual_level_candidates(self, request: RetrievalRequest) -> list[EvidenceDocument]:
        return self._generate_candidate_set(request).dual_docs

    def vector_candidates(self, request: RetrievalRequest) -> list[EvidenceDocument]:
        return self._generate_candidate_set(request).vector_docs

    def bm25_candidates(self, request: RetrievalRequest) -> list[EvidenceDocument]:
        return self._generate_candidate_set(request).bm25_docs

    def constraint_candidates(self, request: RetrievalRequest) -> list[EvidenceDocument]:
        return self._generate_candidate_set(request).constraint_docs

    def hybrid_evidence_search(self, request: RetrievalRequest) -> HybridRetrievalOutcome:
        request = self.prepare_hybrid_request(request)
        control = request.control
        if control is not None:
            control.raise_if_cancelled()
        effective_constraints = request.effective_constraints

        logger.info(
            "Starting hybrid retrieval: rrf_k=%s top_k=%s",
            self.fusion_ranker.rrf_k,
            request.top_k,
        )

        candidates = self.candidate_generator.generate(request)
        if control is not None:
            control.raise_if_cancelled()
        final_docs = self.fusion_ranker.rrf_merge(
            ranked_lists=candidates.ranked_lists,
            top_k=request.top_k,
        )

        if self.retrieval.enable_parent_doc_retrieval:
            if control is not None:
                control.raise_if_cancelled()
            final_docs = self.runtime.attach_parent_evidence_documents(
                final_docs,
                top_n=request.top_k
                if effective_constraints and effective_constraints.has_constraints()
                else None,
            )
        if control is not None:
            control.raise_if_cancelled()

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

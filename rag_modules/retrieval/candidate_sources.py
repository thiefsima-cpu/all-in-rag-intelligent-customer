"""Candidate-source contracts and default hybrid retrieval sources."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import List, Protocol, Sequence

from ..runtime_contracts import HybridCandidateRuntimePort
from .adapters import ConstraintRetriever
from .contracts import EvidenceDocument, RetrievalRequest

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class CandidateSourceSpec:
    """Metadata for a retrieval candidate source."""

    name: str
    rank_name: str
    search_method: str
    search_type: str
    rank_order: int


class RetrievalCandidateSource(Protocol):
    """Stable contract for one hybrid retrieval candidate source."""

    spec: CandidateSourceSpec

    def retrieve(self, request: RetrievalRequest) -> List[EvidenceDocument]: ...


@dataclass(frozen=True, slots=True)
class ConstraintCandidateSource:
    """Constraint-filtered candidate source."""

    constraint_retriever: ConstraintRetriever
    spec: CandidateSourceSpec = CandidateSourceSpec(
        name="constraints",
        rank_name="constraints",
        search_method="constraints",
        search_type="constraint_recipe",
        rank_order=0,
    )

    def retrieve(self, request: RetrievalRequest) -> List[EvidenceDocument]:
        return self.constraint_retriever.search(request)


@dataclass(frozen=True, slots=True)
class DualLevelCandidateSource:
    """Dual-level retrieval source backed by runtime adapters."""

    runtime: HybridCandidateRuntimePort
    spec: CandidateSourceSpec = CandidateSourceSpec(
        name="dual",
        rank_name="dual_level",
        search_method="dual_level",
        search_type="dual_level",
        rank_order=1,
    )

    def retrieve(self, request: RetrievalRequest) -> List[EvidenceDocument]:
        return self.runtime.dual_level_candidates(request)


@dataclass(frozen=True, slots=True)
class VectorCandidateSource:
    """Vector retrieval source backed by runtime adapters."""

    runtime: HybridCandidateRuntimePort
    spec: CandidateSourceSpec = CandidateSourceSpec(
        name="vector",
        rank_name="vector",
        search_method="vector",
        search_type="vector_enhanced",
        rank_order=2,
    )

    def retrieve(self, request: RetrievalRequest) -> List[EvidenceDocument]:
        return self.runtime.vector_candidates(
            request.query,
            top_k=request.effective_candidate_k,
        )


@dataclass(frozen=True, slots=True)
class Bm25CandidateSource:
    """BM25 retrieval source backed by runtime adapters."""

    runtime: HybridCandidateRuntimePort
    spec: CandidateSourceSpec = CandidateSourceSpec(
        name="bm25",
        rank_name="bm25",
        search_method="bm25",
        search_type="bm25",
        rank_order=3,
    )

    def retrieve(self, request: RetrievalRequest) -> List[EvidenceDocument]:
        return self.runtime.bm25_candidates(
            request.query,
            top_k=request.effective_candidate_k,
        )


class HybridCandidateSourceFactory(Protocol):
    """Factory boundary for hybrid retrieval candidate sources."""

    def build(
        self,
        *,
        runtime: HybridCandidateRuntimePort,
        constraint_retriever: ConstraintRetriever,
    ) -> Sequence[RetrievalCandidateSource]: ...


class DefaultHybridCandidateSourceFactory:
    """Default source assembly for hybrid retrieval candidate generation."""

    @staticmethod
    def build(
        *,
        runtime: HybridCandidateRuntimePort,
        constraint_retriever: ConstraintRetriever,
    ) -> Sequence[RetrievalCandidateSource]:
        return (
            ConstraintCandidateSource(constraint_retriever=constraint_retriever),
            DualLevelCandidateSource(runtime=runtime),
            VectorCandidateSource(runtime=runtime),
            Bm25CandidateSource(runtime=runtime),
        )


__all__ = [
    "Bm25CandidateSource",
    "CandidateSourceSpec",
    "ConstraintCandidateSource",
    "DefaultHybridCandidateSourceFactory",
    "DualLevelCandidateSource",
    "HybridCandidateSourceFactory",
    "RetrievalCandidateSource",
    "VectorCandidateSource",
]

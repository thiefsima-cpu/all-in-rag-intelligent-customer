"""Retrieval configuration section model."""

from __future__ import annotations

from typing import Self

from pydantic import Field, model_validator

from ...retrieval.candidate_generator import CandidateSourceDegradationStrategy
from .base import ConfigSection


class RetrievalSettings(ConfigSection):
    top_k: int = 5
    vector_search_ef: int = 128
    vector_search_max_k: int = 50
    rrf_k: int = 60
    hybrid_default_candidate_multiplier: int = 2
    hybrid_default_candidate_min_candidates: int = 10
    hybrid_constraint_candidate_multiplier: int = 6
    hybrid_constraint_candidate_min_candidates: int = 30
    router_combined_candidate_multiplier: int = 6
    router_combined_candidate_min_candidates: int = 30
    router_graph_supplement_candidate_multiplier: int = 2
    router_graph_supplement_candidate_min_candidates: int = 10
    retrieval_preserve_graph_evidence: bool = True
    enable_parent_doc_retrieval: bool = True
    parent_doc_top_n: int = 3
    parent_doc_max_chars: int = 4000
    candidate_source_failure_threshold: int = Field(default=1, ge=1)
    candidate_source_recovery_seconds: float = Field(default=30.0, ge=0.1)
    candidate_source_degradation_strategy: str = "continue"

    @model_validator(mode="after")
    def normalize_degradation_strategy(self) -> Self:
        normalized = self.candidate_source_degradation_strategy.strip().lower() or (
            CandidateSourceDegradationStrategy.CONTINUE.value
        )
        try:
            strategy = CandidateSourceDegradationStrategy(normalized)
        except ValueError:
            supported = ", ".join(strategy.value for strategy in CandidateSourceDegradationStrategy)
            raise ValueError(
                f"candidate_source_degradation_strategy must be one of: {supported}"
            ) from None
        object.__setattr__(
            self,
            "candidate_source_degradation_strategy",
            strategy.value,
        )
        return self


__all__ = ["RetrievalSettings"]

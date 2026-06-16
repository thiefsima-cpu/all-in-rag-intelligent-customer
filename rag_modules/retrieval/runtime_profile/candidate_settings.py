"""Candidate sizing runtime settings."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict

from .shared import _CANDIDATE_DEFAULTS, _as_int


@dataclass
class RetrievalCandidateSizingSettings:
    hybrid_default_multiplier: int = int(_CANDIDATE_DEFAULTS.get("hybrid_default_multiplier", 2))
    hybrid_default_min_candidates: int = int(_CANDIDATE_DEFAULTS.get("hybrid_default_min_candidates", 10))
    hybrid_constraint_multiplier: int = int(_CANDIDATE_DEFAULTS.get("hybrid_constraint_multiplier", 6))
    hybrid_constraint_min_candidates: int = int(_CANDIDATE_DEFAULTS.get("hybrid_constraint_min_candidates", 30))
    combined_multiplier: int = int(_CANDIDATE_DEFAULTS.get("combined_multiplier", 6))
    combined_min_candidates: int = int(_CANDIDATE_DEFAULTS.get("combined_min_candidates", 30))
    graph_supplement_multiplier: int = int(_CANDIDATE_DEFAULTS.get("graph_supplement_multiplier", 2))
    graph_supplement_min_candidates: int = int(_CANDIDATE_DEFAULTS.get("graph_supplement_min_candidates", 10))

    def __post_init__(self) -> None:
        defaults = _CANDIDATE_DEFAULTS
        for field_name in (
            "hybrid_default_multiplier",
            "hybrid_default_min_candidates",
            "hybrid_constraint_multiplier",
            "hybrid_constraint_min_candidates",
            "combined_multiplier",
            "combined_min_candidates",
            "graph_supplement_multiplier",
            "graph_supplement_min_candidates",
        ):
            setattr(
                self,
                field_name,
                _as_int(getattr(self, field_name), int(defaults.get(field_name, getattr(self, field_name))), minimum=1),
            )

    @classmethod
    def from_config(cls, config) -> "RetrievalCandidateSizingSettings":
        defaults = _CANDIDATE_DEFAULTS
        retrieval = config.retrieval
        return cls(
            hybrid_default_multiplier=retrieval.hybrid_default_candidate_multiplier,
            hybrid_default_min_candidates=retrieval.hybrid_default_candidate_min_candidates,
            hybrid_constraint_multiplier=retrieval.hybrid_constraint_candidate_multiplier,
            hybrid_constraint_min_candidates=retrieval.hybrid_constraint_candidate_min_candidates,
            combined_multiplier=retrieval.router_combined_candidate_multiplier,
            combined_min_candidates=retrieval.router_combined_candidate_min_candidates,
            graph_supplement_multiplier=retrieval.router_graph_supplement_candidate_multiplier,
            graph_supplement_min_candidates=retrieval.router_graph_supplement_candidate_min_candidates,
        )

    def hybrid_candidate_k(self, top_k: int, *, constrained: bool) -> int:
        base = _as_int(top_k, 5, minimum=1)
        if constrained:
            return max(base * self.hybrid_constraint_multiplier, self.hybrid_constraint_min_candidates)
        return max(base * self.hybrid_default_multiplier, self.hybrid_default_min_candidates)

    def combined_candidate_k(self, top_k: int) -> int:
        base = _as_int(top_k, 5, minimum=1)
        return max(base * self.combined_multiplier, self.combined_min_candidates)

    def graph_supplement_candidate_k(self, top_k: int) -> int:
        base = _as_int(top_k, 5, minimum=1)
        return max(base * self.graph_supplement_multiplier, self.graph_supplement_min_candidates)

    def to_dict(self) -> Dict[str, Any]:
        return {field.name: getattr(self, field.name) for field in self.__dataclass_fields__.values()}


__all__ = ["RetrievalCandidateSizingSettings"]

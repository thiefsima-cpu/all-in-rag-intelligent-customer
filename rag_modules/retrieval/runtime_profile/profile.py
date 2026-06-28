"""Aggregate retrieval runtime profile."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict

from ...contracts import QueryPlannerRuntimeSettings, QuerySemanticRuntimeSettings
from .candidate_settings import RetrievalCandidateSizingSettings
from .candidate_source_settings import RetrievalCandidateSourceSettings
from .postprocess_settings import RetrievalPostProcessSettings


@dataclass
class RetrievalRuntimeProfile:
    planner: QueryPlannerRuntimeSettings = field(default_factory=QueryPlannerRuntimeSettings)
    semantics: QuerySemanticRuntimeSettings = field(default_factory=QuerySemanticRuntimeSettings)
    candidates: RetrievalCandidateSizingSettings = field(
        default_factory=RetrievalCandidateSizingSettings
    )
    candidate_sources: RetrievalCandidateSourceSettings = field(
        default_factory=RetrievalCandidateSourceSettings
    )
    postprocess: RetrievalPostProcessSettings = field(default_factory=RetrievalPostProcessSettings)

    @classmethod
    def from_config(cls, config) -> "RetrievalRuntimeProfile":
        from .factory import RetrievalRuntimeProfileFactory

        return RetrievalRuntimeProfileFactory().build(config)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "planner": self.planner.to_dict(),
            "semantics": self.semantics.to_dict(),
            "candidates": self.candidates.to_dict(),
            "candidate_sources": self.candidate_sources.to_dict(),
            "postprocess": self.postprocess.to_dict(),
        }


__all__ = ["RetrievalRuntimeProfile"]

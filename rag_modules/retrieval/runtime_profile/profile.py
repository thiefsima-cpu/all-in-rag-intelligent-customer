"""Aggregate retrieval runtime profile."""

from __future__ import annotations

from dataclasses import dataclass

from ...configuration.models import GraphRAGConfig
from ...contracts import QueryPlannerRuntimeSettings, QuerySemanticRuntimeSettings
from ...kernel.json_types import JsonObject, coerce_json_object
from .candidate_settings import RetrievalCandidateSizingSettings
from .candidate_source_settings import RetrievalCandidateSourceSettings
from .postprocess_settings import RetrievalPostProcessSettings


@dataclass
class RetrievalRuntimeProfile:
    planner: QueryPlannerRuntimeSettings
    semantics: QuerySemanticRuntimeSettings
    candidates: RetrievalCandidateSizingSettings
    candidate_sources: RetrievalCandidateSourceSettings
    postprocess: RetrievalPostProcessSettings

    @classmethod
    def from_config(cls, config: GraphRAGConfig) -> "RetrievalRuntimeProfile":
        from .factory import RetrievalRuntimeProfileFactory

        return RetrievalRuntimeProfileFactory().build(config)

    def to_dict(self) -> JsonObject:
        return coerce_json_object(
            {
                "planner": self.planner.to_dict(),
                "semantics": self.semantics.to_dict(),
                "candidates": self.candidates.to_dict(),
                "candidate_sources": self.candidate_sources.to_dict(),
                "postprocess": self.postprocess.to_dict(),
            }
        )


__all__ = ["RetrievalRuntimeProfile"]

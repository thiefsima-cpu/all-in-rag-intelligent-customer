"""Explicit assembly boundary for retrieval runtime profiles."""

from __future__ import annotations

from ...contracts import QueryPlannerRuntimeSettings, QuerySemanticRuntimeSettings
from .candidate_settings import RetrievalCandidateSizingSettings
from .candidate_source_settings import RetrievalCandidateSourceSettings
from .postprocess_settings import RetrievalPostProcessSettings
from .profile import RetrievalRuntimeProfile


class RetrievalRuntimeProfileFactory:
    """Build retrieval runtime profiles from section-native configuration."""

    def build(self, config) -> RetrievalRuntimeProfile:
        return RetrievalRuntimeProfile(
            planner=QueryPlannerRuntimeSettings.from_config(config),
            semantics=QuerySemanticRuntimeSettings.from_config(config),
            candidates=RetrievalCandidateSizingSettings.from_config(config),
            candidate_sources=RetrievalCandidateSourceSettings.from_config(config),
            postprocess=RetrievalPostProcessSettings.from_config(config),
        )


__all__ = ["RetrievalRuntimeProfileFactory"]

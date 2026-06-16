"""Explicit assembly boundary for retrieval runtime profiles."""

from __future__ import annotations

from .candidate_settings import RetrievalCandidateSizingSettings
from .planner_settings import QueryPlannerRuntimeSettings
from .postprocess_settings import RetrievalPostProcessSettings
from .profile import RetrievalRuntimeProfile
from .semantic_settings import QuerySemanticRuntimeSettings


class RetrievalRuntimeProfileFactory:
    """Build retrieval runtime profiles from section-native configuration."""

    def build(self, config) -> RetrievalRuntimeProfile:
        return RetrievalRuntimeProfile(
            planner=QueryPlannerRuntimeSettings.from_config(config),
            semantics=QuerySemanticRuntimeSettings.from_config(config),
            candidates=RetrievalCandidateSizingSettings.from_config(config),
            postprocess=RetrievalPostProcessSettings.from_config(config),
        )


__all__ = ["RetrievalRuntimeProfileFactory"]

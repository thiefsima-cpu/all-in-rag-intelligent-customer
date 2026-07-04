"""Pure shared value types with no subsystem dependencies."""

from .artifacts import (
    ArtifactManifest,
    ArtifactStage,
    DocumentArtifactResult,
    DocumentArtifactSignatures,
    DocumentArtifactStats,
)
from .documents import TextDocument
from .retrieval import CandidateSourceDegradationStrategy
from .routing import RouteStatistics, SearchStrategy

__all__ = [
    "ArtifactManifest",
    "ArtifactStage",
    "CandidateSourceDegradationStrategy",
    "DocumentArtifactResult",
    "DocumentArtifactSignatures",
    "DocumentArtifactStats",
    "RouteStatistics",
    "SearchStrategy",
    "TextDocument",
]

"""Public facade for provider boundaries and default runtime assembly."""

from __future__ import annotations

from .provider_components import (
    ApplicationServiceComponentProvider,
    ArtifactManifestStorePort,
    BuildPipelineComponentProvider,
    DefaultApplicationServiceComponentProvider,
    DefaultBuildPipelineComponentProvider,
    DefaultDiagnosticsComponentProvider,
    DefaultGenerationComponentProvider,
    DefaultInfrastructureComponentProvider,
    DefaultLifecycleComponentProvider,
    DefaultQueryUnderstandingComponentProvider,
    DefaultRetrievalComponentProvider,
    DefaultRuntimeComponentProvider,
    DocumentArtifactCachePort,
    DiagnosticsComponentProvider,
    GenerationComponentProvider,
    InfrastructureComponentProvider,
    LifecycleComponentProvider,
    QueryUnderstandingComponentProvider,
    RetrievalComponentProvider,
    RuntimeComponentProvider,
)
from ..runtime.artifact_ports import RuntimeArtifactAccessPort
from ..runtime.stats_ports import RuntimeStatsAccessPort


def create_default_runtime_provider() -> RuntimeComponentProvider:
    """Create the default composite runtime provider through the app facade."""

    return DefaultRuntimeComponentProvider()

__all__ = [
    "ApplicationServiceComponentProvider",
    "ArtifactManifestStorePort",
    "BuildPipelineComponentProvider",
    "DefaultApplicationServiceComponentProvider",
    "DefaultBuildPipelineComponentProvider",
    "DefaultDiagnosticsComponentProvider",
    "DefaultGenerationComponentProvider",
    "DefaultInfrastructureComponentProvider",
    "DefaultLifecycleComponentProvider",
    "DefaultQueryUnderstandingComponentProvider",
    "DefaultRetrievalComponentProvider",
    "DefaultRuntimeComponentProvider",
    "DocumentArtifactCachePort",
    "DiagnosticsComponentProvider",
    "GenerationComponentProvider",
    "InfrastructureComponentProvider",
    "LifecycleComponentProvider",
    "QueryUnderstandingComponentProvider",
    "RetrievalComponentProvider",
    "RuntimeComponentProvider",
    "RuntimeArtifactAccessPort",
    "RuntimeStatsAccessPort",
    "create_default_runtime_provider",
]

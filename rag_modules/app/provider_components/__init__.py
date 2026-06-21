"""Internal-only provider-component exports.

This package exists to wire the default runtime provider. Repository feature
code should go through ``rag_modules.app.providers`` or other public app-layer
facades instead of importing provider components directly.
"""

from ...runtime.artifact_ports import RuntimeArtifactAccessPort
from ...runtime.stats_ports import RuntimeStatsAccessPort
from .build_pipeline import DefaultBuildPipelineComponentProvider
from .contracts import (
    ApplicationServiceComponentProvider,
    ArtifactManifestStorePort,
    BuildPipelineComponentProvider,
    DiagnosticsComponentProvider,
    DocumentArtifactCachePort,
    GenerationComponentProvider,
    InfrastructureComponentProvider,
    LifecycleComponentProvider,
    QueryUnderstandingComponentProvider,
    RetrievalComponentProvider,
    RuntimeComponentProvider,
)
from .diagnostics import DefaultDiagnosticsComponentProvider
from .generation import DefaultGenerationComponentProvider
from .infrastructure import DefaultInfrastructureComponentProvider
from .lifecycle import DefaultLifecycleComponentProvider
from .query_understanding import DefaultQueryUnderstandingComponentProvider
from .retrieval import DefaultRetrievalComponentProvider
from .runtime import DefaultRuntimeComponentProvider
from .services import DefaultApplicationServiceComponentProvider

INTERNAL_ONLY = True
INTERNAL_ONLY_REASON = (
    "Use rag_modules.app.providers or application assembly facades instead of "
    "importing app.provider_components from feature code."
)

__all__ = [
    "INTERNAL_ONLY",
    "INTERNAL_ONLY_REASON",
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
]

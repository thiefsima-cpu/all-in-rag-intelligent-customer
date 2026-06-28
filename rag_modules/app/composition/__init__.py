"""Internal-only composition-root helpers for build and serving runtimes.

This package is part of the application assembly internals. Repository feature
code should depend on the stable facades in ``rag_modules.app`` instead of
importing composition helpers directly.
"""

from .bootstrapper_composer import (
    BuildBootstrapperComponents,
    BuildBootstrapperComposer,
    GraphBootstrapperSurface,
    GraphBootstrapperSurfaceComposer,
    GraphRAGBootstrapperComponents,
    GraphRAGBootstrapperComposer,
    ServingBootstrapperComponents,
    ServingBootstrapperComposer,
    SystemRuntimeBootstrapServiceComposer,
)
from .build_runtime_executor import BuildRuntimeExecutor
from .build_runtime_factory import BuildRuntimeFactory
from .build_runtime_lifecycle_service import BuildRuntimeLifecycleService
from .provider_resolution import (
    RuntimeComponentProviderResolver,
    RuntimeProviderSurface,
    RuntimeProviderSurfaceResolver,
)
from .runtime_initialization_service import RuntimeInitializationService
from .runtime_lifecycle_service_composer import (
    RuntimeBootstrapperComponents,
    RuntimeLifecycleServiceBundle,
    RuntimeLifecycleServiceComposer,
)
from .runtime_manager import SystemRuntimeManager
from .runtime_readiness_service import RuntimeReadinessService
from .runtime_refresh_service import ServingRuntimeRefreshService
from .runtime_state_store import RuntimeStateStore
from .serving_runtime_factory import ServingRuntimeFactory
from .serving_runtime_lifecycle_service import ServingRuntimeLifecycleService
from .serving_runtime_preparer import ServingRuntimePreparer
from .system_answering_service import SystemAnsweringService
from .system_composer import (
    AdvancedGraphRAGBootstrapperSurface,
    AdvancedGraphRAGSystemComponents,
    AdvancedGraphRAGSystemComposer,
    SystemApplicationServiceComposer,
    SystemApplicationServices,
    SystemBootstrapperSurfaceComposer,
    SystemRuntimeInfrastructure,
    SystemRuntimeInfrastructureComposer,
)
from .system_facade_support import SystemFacadeSupport
from .system_operations_service import SystemOperationsService
from .system_runtime_bootstrap_service import SystemRuntimeBootstrapService

INTERNAL_ONLY = True
INTERNAL_ONLY_REASON = (
    "Use rag_modules.app.assembly, rag_modules.app.system, or rag_modules.app.providers "
    "instead of importing app.composition from feature code."
)

__all__ = [
    "INTERNAL_ONLY",
    "INTERNAL_ONLY_REASON",
    "AdvancedGraphRAGSystemComponents",
    "AdvancedGraphRAGSystemComposer",
    "AdvancedGraphRAGBootstrapperSurface",
    "SystemApplicationServiceComposer",
    "SystemApplicationServices",
    "SystemAnsweringService",
    "SystemBootstrapperSurfaceComposer",
    "SystemFacadeSupport",
    "SystemOperationsService",
    "SystemRuntimeInfrastructure",
    "SystemRuntimeInfrastructureComposer",
    "BuildBootstrapperComponents",
    "BuildBootstrapperComposer",
    "BuildRuntimeExecutor",
    "BuildRuntimeFactory",
    "BuildRuntimeLifecycleService",
    "GraphRAGBootstrapperComponents",
    "GraphRAGBootstrapperComposer",
    "GraphBootstrapperSurface",
    "GraphBootstrapperSurfaceComposer",
    "RuntimeComponentProviderResolver",
    "RuntimeInitializationService",
    "RuntimeBootstrapperComponents",
    "RuntimeLifecycleServiceBundle",
    "RuntimeLifecycleServiceComposer",
    "RuntimeProviderSurface",
    "RuntimeProviderSurfaceResolver",
    "RuntimeReadinessService",
    "ServingRuntimeRefreshService",
    "RuntimeStateStore",
    "ServingBootstrapperComponents",
    "ServingBootstrapperComposer",
    "ServingRuntimeFactory",
    "ServingRuntimeLifecycleService",
    "ServingRuntimePreparer",
    "SystemRuntimeManager",
    "SystemRuntimeBootstrapService",
    "SystemRuntimeBootstrapServiceComposer",
]

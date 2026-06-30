"""Internal support helpers for thin public bootstrapper facades."""

from __future__ import annotations

from dataclasses import fields, is_dataclass
from typing import Any, Generic, TypeVar, cast

from ..configuration.models import GraphRAGConfig
from ..runtime.artifacts import ArtifactManifest
from .bootstrap_facade_contracts import (
    BuildBootstrapperInvocationProtocol,
    GraphBootstrapperInvocationProtocol,
    ServingBootstrapperInvocationProtocol,
)
from .composition.contracts import (
    BuildRuntimeExecutorProtocol,
    BuildRuntimeFactoryProtocol,
    ServingRuntimeLifecycleServiceProtocol,
)
from .composition.shared import ProgressCallback
from .runtime_state import BuildRuntime, ServingRuntime
from .runtime_view import SystemRuntime

_InvocationT = TypeVar("_InvocationT")


class _BoundaryInvocationSupport:
    """Shared delegation helper for bootstrapper invocation strategies."""

    @staticmethod
    def _delegate(boundary: Any, method_name: str, *args: Any, **kwargs: Any) -> Any:
        return getattr(boundary, method_name)(*args, **kwargs)


class BuildBootstrapperInvocationAdapter(
    BuildBootstrapperInvocationProtocol, _BoundaryInvocationSupport
):
    """Invocation strategy for the public build bootstrapper facade."""

    def build_runtime(
        self,
        *,
        factory: BuildRuntimeFactoryProtocol,
        config: GraphRAGConfig | None = None,
        neo4j_manager: Any | None = None,
        data_module: Any | None = None,
        index_module: Any | None = None,
        progress: ProgressCallback = None,
    ) -> BuildRuntime:
        return cast(
            BuildRuntime,
            self._delegate(
                factory,
                "build",
                config,
                neo4j_manager=neo4j_manager,
                data_module=data_module,
                index_module=index_module,
                progress=progress,
            ),
        )

    def build_knowledge_base(
        self,
        *,
        executor: BuildRuntimeExecutorProtocol,
        runtime: BuildRuntime,
        progress: ProgressCallback = None,
    ) -> BuildRuntime:
        return cast(
            BuildRuntime,
            self._delegate(
                executor,
                "build_knowledge_base",
                runtime,
                progress=progress,
            ),
        )

    def rebuild_knowledge_base(
        self,
        *,
        executor: BuildRuntimeExecutorProtocol,
        runtime: BuildRuntime,
        progress: ProgressCallback = None,
    ) -> BuildRuntime:
        return cast(
            BuildRuntime,
            self._delegate(
                executor,
                "rebuild_knowledge_base",
                runtime,
                progress=progress,
            ),
        )


class ServingBootstrapperInvocationAdapter(
    ServingBootstrapperInvocationProtocol,
    _BoundaryInvocationSupport,
):
    """Invocation strategy for the public serving bootstrapper facade."""

    def build_serving_runtime(
        self,
        *,
        lifecycle_service: ServingRuntimeLifecycleServiceProtocol,
        config: GraphRAGConfig | None = None,
        shared_runtime: BuildRuntime | None = None,
        query_tracer: Any | None = None,
        neo4j_manager: Any | None = None,
        data_module: Any | None = None,
        index_module: Any | None = None,
        progress: ProgressCallback = None,
    ) -> ServingRuntime:
        return cast(
            ServingRuntime,
            self._delegate(
                lifecycle_service,
                "build_ready",
                config,
                shared_runtime=shared_runtime,
                query_tracer=query_tracer,
                neo4j_manager=neo4j_manager,
                data_module=data_module,
                index_module=index_module,
                progress=progress,
            ),
        )

    def prepare_serving_runtime(
        self,
        *,
        lifecycle_service: ServingRuntimeLifecycleServiceProtocol,
        runtime: ServingRuntime,
        chunks: Any | None = None,
        artifact_manifest: ArtifactManifest | None = None,
        progress: ProgressCallback = None,
        force: bool = False,
    ) -> ServingRuntime:
        return cast(
            ServingRuntime,
            self._delegate(
                lifecycle_service,
                "prepare",
                runtime,
                chunks=chunks,
                artifact_manifest=artifact_manifest,
                progress=progress,
                force=force,
            ),
        )

    def prepare_serving_runtime_with_shared_runtime(
        self,
        *,
        lifecycle_service: ServingRuntimeLifecycleServiceProtocol,
        runtime: ServingRuntime,
        shared_runtime: BuildRuntime | None = None,
        progress: ProgressCallback = None,
        force: bool = False,
    ) -> ServingRuntime:
        return cast(
            ServingRuntime,
            self._delegate(
                lifecycle_service,
                "prepare_with_shared_runtime",
                runtime,
                shared_runtime=shared_runtime,
                progress=progress,
                force=force,
            ),
        )


class GraphBootstrapperInvocationAdapter(
    GraphBootstrapperInvocationProtocol,
    _BoundaryInvocationSupport,
):
    """Invocation strategy for the public graph bootstrapper facade."""

    def build_system_runtime(
        self,
        *,
        bootstrap_service: Any,
        config: GraphRAGConfig | None = None,
        query_tracer: Any | None = None,
        neo4j_manager: Any | None = None,
        progress: ProgressCallback = None,
    ) -> SystemRuntime:
        return cast(
            SystemRuntime,
            self._delegate(
                bootstrap_service,
                "build",
                config,
                query_tracer=query_tracer,
                neo4j_manager=neo4j_manager,
                progress=progress,
            ),
        )


class _ComposedBootstrapperFacade(Generic[_InvocationT]):
    """Bind composer-resolved dataclass components onto a thin public facade."""

    def __init__(self, *, invocations: _InvocationT) -> None:
        self._invocations = invocations

    def _compose_and_bind(
        self,
        *,
        composer: Any,
        **compose_kwargs: Any,
    ) -> Any:
        components = composer.compose(**compose_kwargs)
        self._bind_components(components)
        return components

    def _bind_components(self, components: Any) -> None:
        if not is_dataclass(components):
            raise TypeError("Bootstrapper components must be dataclass instances.")
        for component_field in fields(components):
            setattr(self, component_field.name, getattr(components, component_field.name))


__all__ = [
    "BuildBootstrapperInvocationAdapter",
    "GraphBootstrapperInvocationAdapter",
    "ServingBootstrapperInvocationAdapter",
    "_ComposedBootstrapperFacade",
]

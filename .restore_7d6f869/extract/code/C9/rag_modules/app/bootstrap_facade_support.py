"""Internal support helpers for thin public bootstrapper facades."""

from __future__ import annotations

from dataclasses import fields, is_dataclass

from ..configuration.models import GraphRAGConfig
from .bootstrap_facade_contracts import (
    BuildBootstrapperInvocationProtocol,
    GraphBootstrapperInvocationProtocol,
    ServingBootstrapperInvocationProtocol,
)
from .composition.shared import ProgressCallback
from .runtime_state import BuildRuntime, ServingRuntime
from .runtime_view import SystemRuntime


class _BoundaryInvocationSupport:
    """Shared delegation helper for bootstrapper invocation strategies."""

    @staticmethod
    def _delegate(boundary, method_name: str, *args, **kwargs):
        return getattr(boundary, method_name)(*args, **kwargs)


class BuildBootstrapperInvocationAdapter(BuildBootstrapperInvocationProtocol, _BoundaryInvocationSupport):
    """Invocation strategy for the public build bootstrapper facade."""

    def build_runtime(
        self,
        *,
        factory,
        config: GraphRAGConfig | None = None,
        neo4j_manager=None,
        data_module=None,
        index_module=None,
        progress: ProgressCallback = None,
    ) -> BuildRuntime:
        return self._delegate(
            factory,
            "build",
            config,
            neo4j_manager=neo4j_manager,
            data_module=data_module,
            index_module=index_module,
            progress=progress,
        )

    def build_knowledge_base(
        self,
        *,
        executor,
        runtime: BuildRuntime,
        progress: ProgressCallback = None,
    ) -> BuildRuntime:
        return self._delegate(
            executor,
            "build_knowledge_base",
            runtime,
            progress=progress,
        )

    def rebuild_knowledge_base(
        self,
        *,
        executor,
        runtime: BuildRuntime,
        progress: ProgressCallback = None,
    ) -> BuildRuntime:
        return self._delegate(
            executor,
            "rebuild_knowledge_base",
            runtime,
            progress=progress,
        )


class ServingBootstrapperInvocationAdapter(
    ServingBootstrapperInvocationProtocol,
    _BoundaryInvocationSupport,
):
    """Invocation strategy for the public serving bootstrapper facade."""

    def build_serving_runtime(
        self,
        *,
        lifecycle_service,
        config: GraphRAGConfig | None = None,
        shared_runtime: BuildRuntime | None = None,
        query_tracer=None,
        neo4j_manager=None,
        data_module=None,
        index_module=None,
        progress: ProgressCallback = None,
    ) -> ServingRuntime:
        return self._delegate(
            lifecycle_service,
            "build_ready",
            config,
            shared_runtime=shared_runtime,
            query_tracer=query_tracer,
            neo4j_manager=neo4j_manager,
            data_module=data_module,
            index_module=index_module,
            progress=progress,
        )

    def prepare_serving_runtime(
        self,
        *,
        lifecycle_service,
        runtime: ServingRuntime,
        chunks=None,
        artifact_manifest=None,
        progress: ProgressCallback = None,
        force: bool = False,
    ) -> ServingRuntime:
        return self._delegate(
            lifecycle_service,
            "prepare",
            runtime,
            chunks=chunks,
            artifact_manifest=artifact_manifest,
            progress=progress,
            force=force,
        )

    def prepare_serving_runtime_with_shared_runtime(
        self,
        *,
        lifecycle_service,
        runtime: ServingRuntime,
        shared_runtime: BuildRuntime | None = None,
        progress: ProgressCallback = None,
        force: bool = False,
    ) -> ServingRuntime:
        return self._delegate(
            lifecycle_service,
            "prepare_with_shared_runtime",
            runtime,
            shared_runtime=shared_runtime,
            progress=progress,
            force=force,
        )


class GraphBootstrapperInvocationAdapter(
    GraphBootstrapperInvocationProtocol,
    _BoundaryInvocationSupport,
):
    """Invocation strategy for the public graph bootstrapper facade."""

    def build_system_runtime(
        self,
        *,
        bootstrap_service,
        config: GraphRAGConfig | None = None,
        query_tracer=None,
        neo4j_manager=None,
        progress: ProgressCallback = None,
    ) -> SystemRuntime:
        return self._delegate(
            bootstrap_service,
            "build",
            config,
            query_tracer=query_tracer,
            neo4j_manager=neo4j_manager,
            progress=progress,
        )


class _ComposedBootstrapperFacade:
    """Bind composer-resolved dataclass components onto a thin public facade."""

    def __init__(self, *, invocations) -> None:
        self._invocations = invocations

    def _compose_and_bind(
        self,
        *,
        composer,
        **compose_kwargs,
    ):
        components = composer.compose(**compose_kwargs)
        self._bind_components(components)
        return components

    def _bind_components(self, components) -> None:
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

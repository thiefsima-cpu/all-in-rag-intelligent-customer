"""Contracts for thin public bootstrapper facade invocation strategies."""

from __future__ import annotations

from typing import Protocol

from ..configuration.models import GraphRAGConfig
from .composition.shared import ProgressCallback
from .runtime_state import BuildRuntime, ServingRuntime
from .runtime_view import SystemRuntime


class BuildBootstrapperInvocationProtocol(Protocol):
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
    ) -> BuildRuntime: ...

    def build_knowledge_base(
        self,
        *,
        executor,
        runtime: BuildRuntime,
        progress: ProgressCallback = None,
    ) -> BuildRuntime: ...

    def rebuild_knowledge_base(
        self,
        *,
        executor,
        runtime: BuildRuntime,
        progress: ProgressCallback = None,
    ) -> BuildRuntime: ...


class ServingBootstrapperInvocationProtocol(Protocol):
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
    ) -> ServingRuntime: ...

    def prepare_serving_runtime(
        self,
        *,
        lifecycle_service,
        runtime: ServingRuntime,
        chunks=None,
        artifact_manifest=None,
        progress: ProgressCallback = None,
        force: bool = False,
    ) -> ServingRuntime: ...

    def prepare_serving_runtime_with_shared_runtime(
        self,
        *,
        lifecycle_service,
        runtime: ServingRuntime,
        shared_runtime: BuildRuntime | None = None,
        progress: ProgressCallback = None,
        force: bool = False,
    ) -> ServingRuntime: ...


class GraphBootstrapperInvocationProtocol(Protocol):
    """Invocation strategy for the public graph bootstrapper facade."""

    def build_system_runtime(
        self,
        *,
        bootstrap_service,
        config: GraphRAGConfig | None = None,
        query_tracer=None,
        neo4j_manager=None,
        progress: ProgressCallback = None,
    ) -> SystemRuntime: ...


__all__ = [
    "BuildBootstrapperInvocationProtocol",
    "GraphBootstrapperInvocationProtocol",
    "ServingBootstrapperInvocationProtocol",
]

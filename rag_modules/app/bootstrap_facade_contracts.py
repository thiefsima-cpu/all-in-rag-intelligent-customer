"""Contracts for thin public bootstrapper facade invocation strategies."""

from __future__ import annotations

from typing import Protocol

from ..configuration.models import GraphRAGConfig
from ..runtime.artifacts import ArtifactManifest
from ..text_document import TextDocument
from .composition.contracts import (
    BuildRuntimeExecutorProtocol,
    BuildRuntimeFactoryProtocol,
    ServingRuntimeLifecycleServiceProtocol,
)
from .composition.shared import ProgressCallback
from .runtime_contracts import (
    GraphDataModulePort,
    Neo4jManagerPort,
    QueryTracerPort,
    VectorIndexModulePort,
)
from .runtime_state import BuildRuntime, ServingRuntime
from .runtime_view import SystemRuntime


class SystemRuntimeBootstrapServiceProtocol(Protocol):
    """Bootstrap service capable of assembling the full runtime surface."""

    def build(
        self,
        config: GraphRAGConfig | None = None,
        *,
        query_tracer: QueryTracerPort | None = None,
        neo4j_manager: Neo4jManagerPort | None = None,
        progress: ProgressCallback = None,
    ) -> SystemRuntime: ...


class BuildBootstrapperInvocationProtocol(Protocol):
    """Invocation strategy for the public build bootstrapper facade."""

    def build_runtime(
        self,
        *,
        factory: BuildRuntimeFactoryProtocol,
        config: GraphRAGConfig | None = None,
        neo4j_manager: Neo4jManagerPort | None = None,
        data_module: GraphDataModulePort | None = None,
        index_module: VectorIndexModulePort | None = None,
        progress: ProgressCallback = None,
    ) -> BuildRuntime: ...

    def build_knowledge_base(
        self,
        *,
        executor: BuildRuntimeExecutorProtocol,
        runtime: BuildRuntime,
        progress: ProgressCallback = None,
    ) -> BuildRuntime: ...

    def rebuild_knowledge_base(
        self,
        *,
        executor: BuildRuntimeExecutorProtocol,
        runtime: BuildRuntime,
        progress: ProgressCallback = None,
    ) -> BuildRuntime: ...


class ServingBootstrapperInvocationProtocol(Protocol):
    """Invocation strategy for the public serving bootstrapper facade."""

    def build_serving_runtime(
        self,
        *,
        lifecycle_service: ServingRuntimeLifecycleServiceProtocol,
        config: GraphRAGConfig | None = None,
        shared_runtime: BuildRuntime | None = None,
        query_tracer: QueryTracerPort | None = None,
        neo4j_manager: Neo4jManagerPort | None = None,
        data_module: GraphDataModulePort | None = None,
        index_module: VectorIndexModulePort | None = None,
        progress: ProgressCallback = None,
    ) -> ServingRuntime: ...

    def prepare_serving_runtime(
        self,
        *,
        lifecycle_service: ServingRuntimeLifecycleServiceProtocol,
        runtime: ServingRuntime,
        chunks: list[TextDocument] | None = None,
        artifact_manifest: ArtifactManifest | None = None,
        progress: ProgressCallback = None,
        force: bool = False,
    ) -> ServingRuntime: ...

    def prepare_serving_runtime_with_shared_runtime(
        self,
        *,
        lifecycle_service: ServingRuntimeLifecycleServiceProtocol,
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
        bootstrap_service: SystemRuntimeBootstrapServiceProtocol,
        config: GraphRAGConfig | None = None,
        query_tracer: QueryTracerPort | None = None,
        neo4j_manager: Neo4jManagerPort | None = None,
        progress: ProgressCallback = None,
    ) -> SystemRuntime: ...


__all__ = [
    "BuildBootstrapperInvocationProtocol",
    "GraphBootstrapperInvocationProtocol",
    "ServingBootstrapperInvocationProtocol",
    "SystemRuntimeBootstrapServiceProtocol",
]

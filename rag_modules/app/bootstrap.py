"""Application bootstrappers kept as thin public facades over composition roots."""

from __future__ import annotations

from typing import Any, Optional

from ..configuration.models import GraphRAGConfig
from ..kernel.artifacts import ArtifactManifest
from .composition import (
    BuildBootstrapperComposer,
    GraphRAGBootstrapperComposer,
    RuntimeComponentProviderResolver,
    ServingBootstrapperComposer,
)
from .composition.build_runtime_executor import BuildRuntimeExecutor
from .composition.build_runtime_factory import BuildRuntimeFactory
from .composition.contracts import (
    BuildRuntimeExecutorProtocol,
    BuildRuntimeFactoryProtocol,
    ServingRuntimeFactoryProtocol,
    ServingRuntimeLifecycleServiceProtocol,
    ServingRuntimePreparerProtocol,
)
from .composition.serving_runtime_factory import ServingRuntimeFactory
from .composition.serving_runtime_preparer import ServingRuntimePreparer
from .composition.shared import ProgressCallback
from .composition.system_runtime_bootstrap_service import SystemRuntimeBootstrapService
from .providers import RuntimeComponentProvider
from .runtime_state import BuildRuntime, ServingRuntime
from .runtime_view import SystemRuntime


class BuildBootstrapper:
    """Public build bootstrapper backed by the canonical build composition root."""

    provider: RuntimeComponentProvider
    executor: BuildRuntimeExecutorProtocol
    factory: BuildRuntimeFactoryProtocol

    def __init__(
        self,
        *,
        provider: RuntimeComponentProvider | None = None,
        factory: BuildRuntimeFactory | None = None,
        executor: BuildRuntimeExecutor | None = None,
        bootstrapper_composer: BuildBootstrapperComposer | None = None,
        provider_resolver: RuntimeComponentProviderResolver | None = None,
    ) -> None:
        components = (bootstrapper_composer or BuildBootstrapperComposer()).compose(
            provider=provider,
            factory=factory,
            executor=executor,
            provider_resolver=provider_resolver,
        )
        self.provider = components.provider
        self.factory = components.factory
        self.executor = components.executor

    def build(
        self,
        config: Optional[GraphRAGConfig] = None,
        *,
        neo4j_manager: Any | None = None,
        data_module: Any | None = None,
        index_module: Any | None = None,
        progress: ProgressCallback = None,
    ) -> BuildRuntime:
        return self.factory.build(
            config,
            neo4j_manager=neo4j_manager,
            data_module=data_module,
            index_module=index_module,
            progress=progress,
        )

    def build_knowledge_base(
        self,
        runtime: BuildRuntime,
        *,
        progress: ProgressCallback = None,
        request_id: str = "",
        build_job_id: str = "",
    ) -> BuildRuntime:
        return self.executor.build_knowledge_base(
            runtime,
            progress=progress,
            request_id=request_id,
            build_job_id=build_job_id,
        )

    def rebuild_knowledge_base(
        self,
        runtime: BuildRuntime,
        *,
        progress: ProgressCallback = None,
        request_id: str = "",
        build_job_id: str = "",
    ) -> BuildRuntime:
        return self.executor.rebuild_knowledge_base(
            runtime,
            progress=progress,
            request_id=request_id,
            build_job_id=build_job_id,
        )


class ServingBootstrapper:
    """Public serving bootstrapper backed by the canonical serving composition root."""

    provider: RuntimeComponentProvider
    factory: ServingRuntimeFactoryProtocol
    preparer: ServingRuntimePreparerProtocol
    lifecycle_service: ServingRuntimeLifecycleServiceProtocol

    def __init__(
        self,
        *,
        provider: RuntimeComponentProvider | None = None,
        factory: ServingRuntimeFactory | None = None,
        preparer: ServingRuntimePreparer | None = None,
        lifecycle_service: ServingRuntimeLifecycleServiceProtocol | None = None,
        bootstrapper_composer: ServingBootstrapperComposer | None = None,
        provider_resolver: RuntimeComponentProviderResolver | None = None,
    ) -> None:
        components = (bootstrapper_composer or ServingBootstrapperComposer()).compose(
            provider=provider,
            factory=factory,
            preparer=preparer,
            lifecycle_service=lifecycle_service,
            provider_resolver=provider_resolver,
        )
        self.provider = components.provider
        self.factory = components.factory
        self.preparer = components.preparer
        self.lifecycle_service = components.lifecycle_service

    def build(
        self,
        config: Optional[GraphRAGConfig] = None,
        *,
        shared_runtime: BuildRuntime | None = None,
        query_tracer: Any | None = None,
        neo4j_manager: Any | None = None,
        data_module: Any | None = None,
        index_module: Any | None = None,
        progress: ProgressCallback = None,
    ) -> ServingRuntime:
        return self.lifecycle_service.build_ready(
            config,
            shared_runtime=shared_runtime,
            query_tracer=query_tracer,
            neo4j_manager=neo4j_manager,
            data_module=data_module,
            index_module=index_module,
            progress=progress,
        )

    def prepare(
        self,
        runtime: ServingRuntime,
        *,
        chunks: Any | None = None,
        artifact_manifest: ArtifactManifest | None = None,
        progress: ProgressCallback = None,
        force: bool = False,
    ) -> ServingRuntime:
        return self.lifecycle_service.prepare(
            runtime,
            chunks=chunks,
            artifact_manifest=artifact_manifest,
            progress=progress,
            force=force,
        )

    def prepare_with_shared_runtime(
        self,
        runtime: ServingRuntime,
        *,
        shared_runtime: BuildRuntime | None = None,
        progress: ProgressCallback = None,
        force: bool = False,
    ) -> ServingRuntime:
        return self.lifecycle_service.prepare_with_shared_runtime(
            runtime,
            shared_runtime=shared_runtime,
            progress=progress,
            force=force,
        )


class GraphRAGBootstrapper:
    """Public bootstrapper facade that exposes split bootstrappers under one surface."""

    provider: RuntimeComponentProvider
    bootstrap_service: SystemRuntimeBootstrapService
    build_bootstrapper: BuildBootstrapper
    serving_bootstrapper: ServingBootstrapper

    def __init__(
        self,
        *,
        provider: RuntimeComponentProvider | None = None,
        build_bootstrapper: BuildBootstrapper | None = None,
        serving_bootstrapper: ServingBootstrapper | None = None,
        bootstrap_service: SystemRuntimeBootstrapService | None = None,
        bootstrapper_composer: GraphRAGBootstrapperComposer | None = None,
        provider_resolver: RuntimeComponentProviderResolver | None = None,
    ) -> None:
        components = (bootstrapper_composer or GraphRAGBootstrapperComposer()).compose(
            provider=provider,
            build_bootstrapper=build_bootstrapper,
            serving_bootstrapper=serving_bootstrapper,
            bootstrap_service=bootstrap_service,
            provider_resolver=provider_resolver,
        )
        self.provider = components.provider
        self.build_bootstrapper = components.build_bootstrapper
        self.serving_bootstrapper = components.serving_bootstrapper
        self.bootstrap_service = components.bootstrap_service

    def build(
        self,
        config: Optional[GraphRAGConfig] = None,
        *,
        query_tracer: Any | None = None,
        neo4j_manager: Any | None = None,
        progress: ProgressCallback = None,
    ) -> SystemRuntime:
        return self.bootstrap_service.build(
            config,
            query_tracer=query_tracer,
            neo4j_manager=neo4j_manager,
            progress=progress,
        )

"""Application bootstrappers kept as thin public facades over composition roots."""

from __future__ import annotations

from typing import Any, Optional

from ..configuration.models import GraphRAGConfig
from ..runtime.artifacts import ArtifactManifest
from .bootstrap_facade_support import (
    BuildBootstrapperInvocationAdapter,
    GraphBootstrapperInvocationAdapter,
    ServingBootstrapperInvocationAdapter,
    _ComposedBootstrapperFacade,
)
from .composition import (
    BuildBootstrapperComposer,
    GraphRAGBootstrapperComposer,
    RuntimeComponentProviderResolver,
    ServingBootstrapperComposer,
)
from .composition.build_runtime_executor import BuildRuntimeExecutor
from .composition.build_runtime_factory import BuildRuntimeFactory
from .composition.contracts import ServingRuntimeLifecycleServiceProtocol
from .composition.serving_runtime_factory import ServingRuntimeFactory
from .composition.serving_runtime_preparer import ServingRuntimePreparer
from .composition.shared import ProgressCallback
from .composition.system_runtime_bootstrap_service import SystemRuntimeBootstrapService
from .provider_components.contracts import RuntimeComponentProvider
from .runtime_state import BuildRuntime, ServingRuntime
from .runtime_view import SystemRuntime


class BuildBootstrapper(_ComposedBootstrapperFacade[BuildBootstrapperInvocationAdapter]):
    """Public build bootstrapper backed by the canonical build composition root."""

    executor: BuildRuntimeExecutor
    factory: BuildRuntimeFactory

    def __init__(
        self,
        *,
        provider: RuntimeComponentProvider | None = None,
        factory: BuildRuntimeFactory | None = None,
        executor: BuildRuntimeExecutor | None = None,
        bootstrapper_composer: BuildBootstrapperComposer | None = None,
        provider_resolver: RuntimeComponentProviderResolver | None = None,
    ) -> None:
        super().__init__(invocations=BuildBootstrapperInvocationAdapter())
        self._compose_and_bind(
            composer=bootstrapper_composer or BuildBootstrapperComposer(),
            provider=provider,
            factory=factory,
            executor=executor,
            provider_resolver=provider_resolver,
        )

    def build(
        self,
        config: Optional[GraphRAGConfig] = None,
        *,
        neo4j_manager: Any | None = None,
        data_module: Any | None = None,
        index_module: Any | None = None,
        progress: ProgressCallback = None,
    ) -> BuildRuntime:
        return self._invocations.build_runtime(
            factory=self.factory,
            config=config,
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
    ) -> BuildRuntime:
        return self._invocations.build_knowledge_base(
            executor=self.executor,
            runtime=runtime,
            progress=progress,
        )

    def rebuild_knowledge_base(
        self,
        runtime: BuildRuntime,
        *,
        progress: ProgressCallback = None,
    ) -> BuildRuntime:
        return self._invocations.rebuild_knowledge_base(
            executor=self.executor,
            runtime=runtime,
            progress=progress,
        )


class ServingBootstrapper(_ComposedBootstrapperFacade[ServingBootstrapperInvocationAdapter]):
    """Public serving bootstrapper backed by the canonical serving composition root."""

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
        super().__init__(invocations=ServingBootstrapperInvocationAdapter())
        self._compose_and_bind(
            composer=bootstrapper_composer or ServingBootstrapperComposer(),
            provider=provider,
            factory=factory,
            preparer=preparer,
            lifecycle_service=lifecycle_service,
            provider_resolver=provider_resolver,
        )

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
        return self._invocations.build_serving_runtime(
            lifecycle_service=self.lifecycle_service,
            config=config,
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
        return self._invocations.prepare_serving_runtime(
            lifecycle_service=self.lifecycle_service,
            runtime=runtime,
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
        return self._invocations.prepare_serving_runtime_with_shared_runtime(
            lifecycle_service=self.lifecycle_service,
            runtime=runtime,
            shared_runtime=shared_runtime,
            progress=progress,
            force=force,
        )


class GraphRAGBootstrapper(_ComposedBootstrapperFacade[GraphBootstrapperInvocationAdapter]):
    """Compatibility facade that exposes split bootstrappers under one surface."""

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
        super().__init__(invocations=GraphBootstrapperInvocationAdapter())
        self._compose_and_bind(
            composer=bootstrapper_composer or GraphRAGBootstrapperComposer(),
            provider=provider,
            build_bootstrapper=build_bootstrapper,
            serving_bootstrapper=serving_bootstrapper,
            bootstrap_service=bootstrap_service,
            provider_resolver=provider_resolver,
        )

    def build(
        self,
        config: Optional[GraphRAGConfig] = None,
        *,
        query_tracer: Any | None = None,
        neo4j_manager: Any | None = None,
        progress: ProgressCallback = None,
    ) -> SystemRuntime:
        return self._invocations.build_system_runtime(
            bootstrap_service=self.bootstrap_service,
            config=config,
            query_tracer=query_tracer,
            neo4j_manager=neo4j_manager,
            progress=progress,
        )

"""Serving-runtime lifecycle coordination over serving composition roots."""

from __future__ import annotations

from ...configuration.models import GraphRAGConfig
from ..runtime_state import BuildRuntime, ServingRuntime
from .contracts import ServingRuntimeFactoryProtocol, ServingRuntimePreparerProtocol
from .shared import ProgressCallback


class ServingRuntimeLifecycleService:
    """Own serving-runtime build-ready and prepare flows outside public facades."""

    def __init__(
        self,
        *,
        serving_runtime_factory: ServingRuntimeFactoryProtocol,
        serving_runtime_preparer: ServingRuntimePreparerProtocol,
    ) -> None:
        self.serving_runtime_factory = serving_runtime_factory
        self.serving_runtime_preparer = serving_runtime_preparer

    def build_ready(
        self,
        config: GraphRAGConfig | None = None,
        *,
        shared_runtime: BuildRuntime | None = None,
        query_tracer=None,
        neo4j_manager=None,
        data_module=None,
        index_module=None,
        progress: ProgressCallback = None,
    ) -> ServingRuntime:
        runtime = self.serving_runtime_factory.build(
            config,
            shared_runtime=shared_runtime,
            query_tracer=query_tracer,
            neo4j_manager=neo4j_manager,
            data_module=data_module,
            index_module=index_module,
            progress=progress,
        )
        return self.serving_runtime_preparer.prepare_with_shared_runtime(
            runtime,
            shared_runtime=shared_runtime,
            progress=progress,
        )

    def prepare(
        self,
        runtime: ServingRuntime,
        *,
        chunks=None,
        artifact_manifest=None,
        progress: ProgressCallback = None,
        force: bool = False,
    ) -> ServingRuntime:
        return self.serving_runtime_preparer.prepare(
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
        return self.serving_runtime_preparer.prepare_with_shared_runtime(
            runtime,
            shared_runtime=shared_runtime,
            progress=progress,
            force=force,
        )


__all__ = ["ServingRuntimeLifecycleService"]

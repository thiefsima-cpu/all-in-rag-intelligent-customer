"""Compatibility shim for the retired serving-runtime assembler layer."""

from __future__ import annotations

from ...configuration.models import GraphRAGConfig
from ..runtime_state import BuildRuntime, ServingRuntime
from .serving_runtime_factory import ServingRuntimeFactory
from .shared import ProgressCallback


class ServingRuntimeAssembler(ServingRuntimeFactory):
    """Backward-compatible alias for callers still using ``assemble``."""

    def assemble(
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
        return self.build(
            config=config,
            shared_runtime=shared_runtime,
            query_tracer=query_tracer,
            neo4j_manager=neo4j_manager,
            data_module=data_module,
            index_module=index_module,
            progress=progress,
        )


__all__ = ["ServingRuntimeAssembler"]

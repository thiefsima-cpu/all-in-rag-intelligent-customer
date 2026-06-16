"""Compatibility shim for the retired build-runtime assembler layer."""

from __future__ import annotations

from ...configuration.models import GraphRAGConfig
from ..runtime_state import BuildRuntime
from .build_runtime_factory import BuildRuntimeFactory
from .shared import ProgressCallback


class BuildRuntimeAssembler(BuildRuntimeFactory):
    """Backward-compatible alias for callers still using ``assemble``."""

    def assemble(
        self,
        config: GraphRAGConfig | None = None,
        *,
        neo4j_manager=None,
        data_module=None,
        index_module=None,
        progress: ProgressCallback = None,
    ) -> BuildRuntime:
        return self.build(
            config=config,
            neo4j_manager=neo4j_manager,
            data_module=data_module,
            index_module=index_module,
            progress=progress,
        )


__all__ = ["BuildRuntimeAssembler"]

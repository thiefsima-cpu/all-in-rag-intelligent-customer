"""Execute offline knowledge-base build workflows over an assembled runtime."""

from __future__ import annotations

from ..runtime_state import BuildRuntime
from .shared import ProgressCallback


class BuildRuntimeExecutor:
    """Execute build and rebuild operations using the build runtime service graph."""

    def build_knowledge_base(
        self,
        runtime: BuildRuntime,
        *,
        progress: ProgressCallback = None,
    ) -> BuildRuntime:
        runtime.knowledge_base_service.build(progress=progress)
        runtime.artifact_manifest = runtime.knowledge_base_service.artifact_manifest
        return runtime

    def rebuild_knowledge_base(
        self,
        runtime: BuildRuntime,
        *,
        progress: ProgressCallback = None,
    ) -> BuildRuntime:
        runtime.knowledge_base_service.rebuild(progress=progress)
        runtime.artifact_manifest = runtime.knowledge_base_service.artifact_manifest
        return runtime


__all__ = ["BuildRuntimeExecutor"]

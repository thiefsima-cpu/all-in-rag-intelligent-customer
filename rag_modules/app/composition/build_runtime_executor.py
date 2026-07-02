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
        request_id: str = "",
        build_job_id: str = "",
    ) -> BuildRuntime:
        knowledge_base_service = runtime.knowledge_base_service
        if knowledge_base_service is None:
            raise ValueError("Build runtime is missing a knowledge base service.")
        knowledge_base_service.build(
            progress=progress,
            request_id=request_id,
            build_job_id=build_job_id,
        )
        runtime.artifact_manifest = knowledge_base_service.artifact_manifest
        return runtime

    def rebuild_knowledge_base(
        self,
        runtime: BuildRuntime,
        *,
        progress: ProgressCallback = None,
        request_id: str = "",
        build_job_id: str = "",
    ) -> BuildRuntime:
        knowledge_base_service = runtime.knowledge_base_service
        if knowledge_base_service is None:
            raise ValueError("Build runtime is missing a knowledge base service.")
        knowledge_base_service.rebuild(
            progress=progress,
            request_id=request_id,
            build_job_id=build_job_id,
        )
        runtime.artifact_manifest = knowledge_base_service.artifact_manifest
        return runtime


__all__ = ["BuildRuntimeExecutor"]

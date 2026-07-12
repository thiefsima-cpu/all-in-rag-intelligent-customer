"""Knowledge-base lifecycle application use case."""

from __future__ import annotations

from ..kernel.artifacts import ArtifactManifest
from .ports import CloseablePort, KnowledgeBaseBuildWorkflowPort, ProgressCallback


class KnowledgeBaseService:
    """Delegate build operations to an injected workflow and own its resources."""

    def __init__(
        self,
        *,
        workflow: KnowledgeBaseBuildWorkflowPort,
        closeables: tuple[CloseablePort, ...] = (),
    ) -> None:
        self.workflow = workflow
        self.closeables = closeables

    @property
    def artifacts_ready(self) -> bool:
        return self.workflow.artifacts_ready

    @property
    def system_ready(self) -> bool:
        return self.artifacts_ready

    @property
    def artifact_manifest(self) -> ArtifactManifest:
        return self.workflow.artifact_manifest

    @artifact_manifest.setter
    def artifact_manifest(self, manifest: ArtifactManifest) -> None:
        self.workflow.artifact_manifest = manifest

    def build(
        self,
        progress: ProgressCallback = None,
        *,
        request_id: str = "",
        build_job_id: str = "",
    ) -> None:
        self.workflow.build(
            progress=progress,
            request_id=request_id,
            build_job_id=build_job_id,
        )

    def rebuild(
        self,
        progress: ProgressCallback = None,
        *,
        request_id: str = "",
        build_job_id: str = "",
    ) -> None:
        self.workflow.rebuild(
            progress=progress,
            request_id=request_id,
            build_job_id=build_job_id,
        )

    def show_stats(self, progress: ProgressCallback = None) -> None:
        self.workflow.show_stats(progress)

    def close(self) -> None:
        for resource in self.closeables:
            resource.close()


__all__ = ["KnowledgeBaseService"]

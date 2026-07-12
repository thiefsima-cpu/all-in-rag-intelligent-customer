from __future__ import annotations

from rag_modules.application.knowledge_base import KnowledgeBaseService
from rag_modules.kernel.artifacts import ArtifactManifest


class _FakeBuildWorkflow:
    def __init__(self) -> None:
        self.artifact_manifest = ArtifactManifest.missing(manifest_path="manifest.json")
        self.calls: list[tuple[str, object]] = []

    @property
    def artifacts_ready(self) -> bool:
        return self.artifact_manifest.is_ready

    def build(
        self,
        progress=None,
        *,
        force_rebuild=False,
        request_id="",
        build_job_id="",
    ) -> ArtifactManifest:
        del force_rebuild
        self.calls.append(("build", (progress, request_id, build_job_id)))
        return self.artifact_manifest

    def rebuild(self, progress=None, *, request_id="", build_job_id="") -> ArtifactManifest:
        self.calls.append(("rebuild", (progress, request_id, build_job_id)))
        return self.artifact_manifest

    def show_stats(self, progress=None) -> None:
        self.calls.append(("show_stats", progress))


class _FakeCloseable:
    def __init__(self) -> None:
        self.close_calls = 0

    def close(self) -> None:
        self.close_calls += 1


def test_knowledge_base_service_delegates_to_injected_workflow() -> None:
    workflow = _FakeBuildWorkflow()
    resource = _FakeCloseable()
    service = KnowledgeBaseService(workflow=workflow, closeables=(resource,))

    def progress(message: str) -> None:
        del message

    service.build(progress, request_id="request-1", build_job_id="job-1")
    service.rebuild(progress, request_id="request-2", build_job_id="job-2")
    service.show_stats(progress)
    service.close()

    assert workflow.calls == [
        ("build", (progress, "request-1", "job-1")),
        ("rebuild", (progress, "request-2", "job-2")),
        ("show_stats", progress),
    ]
    assert resource.close_calls == 1
    assert service.artifact_manifest is workflow.artifact_manifest

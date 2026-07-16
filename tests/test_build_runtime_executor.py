from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from rag_modules.app.composition.build_runtime_executor import BuildRuntimeExecutor
from rag_modules.app.runtime_state import BuildRuntime
from rag_modules.configuration.testing import build_test_config
from rag_modules.kernel.artifacts import ArtifactManifest


def _runtime(service: object | None) -> BuildRuntime:
    return BuildRuntime(
        config=build_test_config(),
        neo4j_manager=SimpleNamespace(),
        data_module=SimpleNamespace(),
        index_module=SimpleNamespace(),
        knowledge_base_service=service,
    )


@pytest.mark.parametrize(
    ("method_name", "service_method"),
    [
        ("build_knowledge_base", "build"),
        ("rebuild_knowledge_base", "rebuild"),
    ],
)
def test_executor_delegates_once_despite_empty_result_and_refreshes_manifest(
    method_name: str,
    service_method: str,
) -> None:
    manifest = ArtifactManifest(
        stage="ready",
        total_documents=1,
        total_chunks=1,
        vector_rows=1,
    )
    service = SimpleNamespace(
        build=Mock(return_value=None),
        rebuild=Mock(return_value=None),
        artifact_manifest=manifest,
    )
    runtime = _runtime(service)
    progress = Mock()

    result = getattr(BuildRuntimeExecutor(), method_name)(
        runtime,
        progress=progress,
        request_id="request-1",
        build_job_id="job-1",
    )

    getattr(service, service_method).assert_called_once_with(
        progress=progress,
        request_id="request-1",
        build_job_id="job-1",
    )
    unused_method = "rebuild" if service_method == "build" else "build"
    getattr(service, unused_method).assert_not_called()
    assert result is runtime
    assert runtime.artifact_manifest is manifest


@pytest.mark.parametrize(
    ("method_name", "service_method"),
    [
        ("build_knowledge_base", "build"),
        ("rebuild_knowledge_base", "rebuild"),
    ],
)
def test_executor_forwards_default_options(method_name: str, service_method: str) -> None:
    service = SimpleNamespace(
        build=Mock(return_value=None),
        rebuild=Mock(return_value=None),
        artifact_manifest=ArtifactManifest(),
    )

    getattr(BuildRuntimeExecutor(), method_name)(_runtime(service))

    getattr(service, service_method).assert_called_once_with(
        progress=None,
        request_id="",
        build_job_id="",
    )


@pytest.mark.parametrize(
    "method_name",
    ["build_knowledge_base", "rebuild_knowledge_base"],
)
def test_executor_rejects_runtime_without_knowledge_base_service(method_name: str) -> None:
    runtime = _runtime(None)
    initial_manifest = runtime.artifact_manifest

    with pytest.raises(ValueError, match="missing a knowledge base service"):
        getattr(BuildRuntimeExecutor(), method_name)(runtime)

    assert runtime.artifact_manifest is initial_manifest


@pytest.mark.parametrize(
    ("method_name", "service_method"),
    [
        ("build_knowledge_base", "build"),
        ("rebuild_knowledge_base", "rebuild"),
    ],
)
def test_executor_propagates_service_failure_without_refreshing_manifest(
    method_name: str,
    service_method: str,
) -> None:
    error = RuntimeError(f"{service_method} failed")
    service = SimpleNamespace(
        build=Mock(return_value=None),
        rebuild=Mock(return_value=None),
        artifact_manifest=ArtifactManifest(stage="failed"),
    )
    getattr(service, service_method).side_effect = error
    runtime = _runtime(service)
    initial_manifest = runtime.artifact_manifest

    with pytest.raises(RuntimeError, match=rf"{service_method} failed") as exc_info:
        getattr(BuildRuntimeExecutor(), method_name)(runtime)

    assert exc_info.value is error
    getattr(service, service_method).assert_called_once_with(
        progress=None,
        request_id="",
        build_job_id="",
    )
    assert runtime.artifact_manifest is initial_manifest

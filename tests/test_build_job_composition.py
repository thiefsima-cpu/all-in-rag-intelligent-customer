from __future__ import annotations

from typing import cast

from rag_modules.app.application_protocol import GraphRAGApplication
from rag_modules.app.composition.build_jobs import compose_build_job_application
from rag_modules.app.runtime_operations import RuntimeOperationCoordinator
from rag_modules.configuration.testing import build_test_config
from rag_modules.contracts.build_jobs import (
    BuildJobRepositoryDiagnostics,
    BuildJobRepositoryPort,
)


class _ExternalRepository:
    list_default_limit = 25

    def diagnostics(self) -> BuildJobRepositoryDiagnostics:
        return BuildJobRepositoryDiagnostics()


def test_build_job_composition_accepts_an_external_repository_factory() -> None:
    config = build_test_config(
        {
            "api": {"build_job_runner_backend": "external_worker"},
            "observability": {"otel_service_name": "external-build-repository-test"},
        }
    )
    repository = _ExternalRepository()
    received_configs = []

    service = compose_build_job_application(
        system=cast(GraphRAGApplication, object()),
        config=config,
        coordinator=RuntimeOperationCoordinator(),
        repository_factory=lambda received: (
            received_configs.append(received) or cast(BuildJobRepositoryPort, repository)
        ),
    )

    assert received_configs == [config]
    assert service.diagnostics() == BuildJobRepositoryDiagnostics()

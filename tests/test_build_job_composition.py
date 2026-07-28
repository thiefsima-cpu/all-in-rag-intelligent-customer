from __future__ import annotations

from types import SimpleNamespace
from typing import cast
from unittest.mock import Mock, patch

import pytest

from rag_modules.app.application_protocol import GraphRAGApplication
from rag_modules.app.composition import build_jobs as composition
from rag_modules.app.composition.build_jobs import compose_build_job_application
from rag_modules.app.runtime_operations import RuntimeOperationCoordinator
from rag_modules.contracts.build_jobs import (
    BuildJobRepositoryDiagnostics,
    BuildJobRepositoryError,
    BuildJobRepositoryPort,
    BuildJobRepositorySettings,
)
from tests.configuration_test_helpers import build_test_config


class _ExternalRepository:
    list_default_limit = 25

    def diagnostics(self) -> BuildJobRepositoryDiagnostics:
        return BuildJobRepositoryDiagnostics()


class _NoopRunner:
    def start(self) -> None:
        return None

    def schedule(self, _job_id: object) -> None:
        return None

    def notify_cancellation(self, _job_id: object) -> None:
        return None

    def shutdown(self) -> None:
        return None


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


def test_factory_precedes_postgresql_validation() -> None:
    config = build_test_config().with_overrides(
        {
            "api": {
                "build_job_repository_backend": "postgresql",
                "build_job_runner_backend": "external_worker",
            },
            "storage": {"build_job_postgres_dsn": ""},
        }
    )
    repository = _ExternalRepository()

    service = compose_build_job_application(
        system=cast(GraphRAGApplication, object()),
        config=config,
        coordinator=RuntimeOperationCoordinator(),
        repository_factory=lambda _: cast(BuildJobRepositoryPort, repository),
    )

    assert service.diagnostics() == repository.diagnostics()


def test_builtin_file_backend_migrates_and_maps_repository_settings() -> None:
    config = build_test_config(
        {
            "api": {
                "build_job_runner_backend": "external_worker",
                "build_job_retention_limit": 17,
                "build_job_list_default_limit": 3,
                "build_job_list_max_limit": 9,
                "build_job_lease_seconds": 24.0,
                "build_job_audit_retention_days": 31,
            }
        }
    )
    repository = _ExternalRepository()
    migrator = Mock()
    file_factory = Mock(return_value=repository)
    runtime_build_jobs = SimpleNamespace(
        BuildJobStoreMigrator=Mock(return_value=migrator),
        FileBuildJobRepository=file_factory,
        ExternalBuildJobQueueRunner=_NoopRunner,
    )

    with patch.object(composition, "_runtime_build_jobs_module", return_value=runtime_build_jobs):
        service = compose_build_job_application(
            system=cast(GraphRAGApplication, object()),
            config=config,
            coordinator=RuntimeOperationCoordinator(),
        )

    assert service.diagnostics() == repository.diagnostics()
    migrator.migrate.assert_called_once_with()
    assert file_factory.call_args.kwargs["settings"] == BuildJobRepositorySettings(
        retention_limit=17,
        list_default_limit=3,
        list_max_limit=9,
        lease_seconds=24.0,
        audit_retention_days=31,
    )


def test_builtin_postgresql_backend_maps_settings_without_file_migration() -> None:
    config = build_test_config().with_overrides(
        {
            "api": {
                "build_job_repository_backend": "postgresql",
                "build_job_runner_backend": "external_worker",
                "build_job_retention_limit": 17,
                "build_job_list_default_limit": 3,
                "build_job_list_max_limit": 9,
                "build_job_lease_seconds": 24.0,
                "build_job_audit_retention_days": 31,
                "build_job_postgres_pool_min_size": 2,
                "build_job_postgres_pool_max_size": 7,
                "build_job_postgres_pool_timeout_seconds": 4.5,
            },
            "storage": {"build_job_postgres_dsn": "postgresql://configured.invalid/build_jobs"},
        }
    )
    repository = _ExternalRepository()
    postgres_factory = Mock(return_value=repository)
    runtime_build_jobs = SimpleNamespace(
        PostgresBuildJobRepository=postgres_factory,
        BuildJobStoreMigrator=Mock(),
        FileBuildJobRepository=Mock(),
        ExternalBuildJobQueueRunner=_NoopRunner,
    )

    with patch.object(composition, "_runtime_build_jobs_module", return_value=runtime_build_jobs):
        service = compose_build_job_application(
            system=cast(GraphRAGApplication, object()),
            config=config,
            coordinator=RuntimeOperationCoordinator(),
        )

    assert service.diagnostics() == repository.diagnostics()
    runtime_build_jobs.BuildJobStoreMigrator.assert_not_called()
    runtime_build_jobs.FileBuildJobRepository.assert_not_called()
    assert postgres_factory.call_args.args == ("postgresql://configured.invalid/build_jobs",)
    assert postgres_factory.call_args.kwargs == {
        "now": composition._utc_now,
        "settings": BuildJobRepositorySettings(
            retention_limit=17,
            list_default_limit=3,
            list_max_limit=9,
            lease_seconds=24.0,
            audit_retention_days=31,
        ),
        "pool_min_size": 2,
        "pool_max_size": 7,
        "pool_timeout_seconds": 4.5,
    }


def test_postgresql_backend_without_dsn_fails_closed_without_file_fallback() -> None:
    config = build_test_config().with_overrides(
        {
            "api": {"build_job_repository_backend": "postgresql"},
            "storage": {"build_job_postgres_dsn": "   "},
        }
    )
    runtime_build_jobs = SimpleNamespace(
        PostgresBuildJobRepository=Mock(),
        BuildJobStoreMigrator=Mock(),
        FileBuildJobRepository=Mock(),
    )

    with pytest.raises(BuildJobRepositoryError, match=r"^Build job PostgreSQL DSN is required\.$"):
        composition._compose_repository(
            runtime_build_jobs=runtime_build_jobs,
            config=config,
            repository_factory=None,
        )

    runtime_build_jobs.PostgresBuildJobRepository.assert_not_called()
    runtime_build_jobs.BuildJobStoreMigrator.assert_not_called()
    runtime_build_jobs.FileBuildJobRepository.assert_not_called()


def test_postgresql_constructor_failure_does_not_fallback_to_file() -> None:
    config = build_test_config().with_overrides(
        {
            "api": {"build_job_repository_backend": "postgresql"},
            "storage": {"build_job_postgres_dsn": "postgresql://configured.invalid/build_jobs"},
        }
    )
    runtime_build_jobs = SimpleNamespace(
        PostgresBuildJobRepository=Mock(
            side_effect=BuildJobRepositoryError("Build job PostgreSQL schema is not ready.")
        ),
        BuildJobStoreMigrator=Mock(),
        FileBuildJobRepository=Mock(),
    )

    with pytest.raises(
        BuildJobRepositoryError, match=r"^Build job PostgreSQL schema is not ready\.$"
    ):
        composition._compose_repository(
            runtime_build_jobs=runtime_build_jobs,
            config=config,
            repository_factory=None,
        )

    runtime_build_jobs.BuildJobStoreMigrator.assert_not_called()
    runtime_build_jobs.FileBuildJobRepository.assert_not_called()

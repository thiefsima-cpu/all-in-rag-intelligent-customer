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
from rag_modules.runtime.build_jobs.postgres.repository import PostgresBuildJobObservers
from tests.configuration_test_helpers import build_test_config


class _ExternalRepository:
    list_default_limit = 25

    def __init__(self, *, close_exception: Exception | None = None) -> None:
        self.close_calls = 0
        self.close_exception = close_exception

    def diagnostics(self) -> BuildJobRepositoryDiagnostics:
        return BuildJobRepositoryDiagnostics()

    def close(self) -> None:
        self.close_calls += 1
        if self.close_exception is not None:
            raise self.close_exception


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
    kwargs = postgres_factory.call_args.kwargs
    observers = kwargs.pop("observers")
    assert isinstance(observers, PostgresBuildJobObservers)
    assert kwargs == {
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


def test_postgresql_observers_bind_only_safe_telemetry_recorders() -> None:
    telemetry = Mock()

    observers = composition._postgres_build_job_observers(telemetry)

    assert observers is not None
    observers.operation("postgresql", "submit", "success", 0.25)
    observers.claim("postgresql", "empty")
    observers.error("postgresql", "connection")
    observers.retention("postgresql", "purged", 2)

    telemetry.record_build_job_repository_operation.assert_called_once_with(
        backend="postgresql",
        operation="submit",
        outcome="success",
        duration_seconds=0.25,
    )
    telemetry.record_build_job_claim.assert_called_once_with(backend="postgresql", outcome="empty")
    telemetry.record_build_job_repository_error.assert_called_once_with(
        backend="postgresql",
        category="connection",
    )
    telemetry.record_build_job_retention.assert_called_once_with(
        backend="postgresql",
        action="purged",
        count=2,
    )


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


def test_api_composition_closes_repository_when_telemetry_or_runner_construction_fails() -> None:
    config = build_test_config().with_overrides(
        {
            "api": {
                "build_job_repository_backend": "postgresql",
                "build_job_runner_backend": "external_worker",
            },
            "storage": {"build_job_postgres_dsn": "postgresql://configured.invalid/build_jobs"},
        }
    )
    for failure_point in ("telemetry", "runner"):
        repository = _ExternalRepository(
            close_exception=RuntimeError("close failed") if failure_point == "runner" else None
        )
        runtime_build_jobs = SimpleNamespace(
            PostgresBuildJobRepository=Mock(return_value=repository),
            BuildJobStoreMigrator=Mock(),
            FileBuildJobRepository=Mock(),
            ExternalBuildJobQueueRunner=Mock(side_effect=RuntimeError("runner failed")),
        )
        telemetry = Mock()

        with (
            patch.object(
                composition, "_runtime_build_jobs_module", return_value=runtime_build_jobs
            ),
            patch.object(
                composition,
                "get_runtime_telemetry",
                side_effect=RuntimeError("telemetry failed")
                if failure_point == "telemetry"
                else lambda _: telemetry,
            ),
            pytest.raises(
                RuntimeError,
                match="telemetry failed" if failure_point == "telemetry" else "runner failed",
            ),
        ):
            compose_build_job_application(
                system=cast(GraphRAGApplication, object()),
                config=config,
                coordinator=RuntimeOperationCoordinator(),
            )

        assert repository.close_calls == (0 if failure_point == "telemetry" else 1)
        runtime_build_jobs.FileBuildJobRepository.assert_not_called()
        runtime_build_jobs.BuildJobStoreMigrator.assert_not_called()


def test_api_composition_closes_repository_when_service_construction_fails() -> None:
    config = build_test_config().with_overrides(
        {
            "api": {
                "build_job_repository_backend": "postgresql",
                "build_job_runner_backend": "external_worker",
            },
            "storage": {"build_job_postgres_dsn": "postgresql://configured.invalid/build_jobs"},
        }
    )
    repository = _ExternalRepository()
    runtime_build_jobs = SimpleNamespace(
        PostgresBuildJobRepository=Mock(return_value=repository),
        BuildJobStoreMigrator=Mock(),
        FileBuildJobRepository=Mock(),
        ExternalBuildJobQueueRunner=_NoopRunner,
    )

    with (
        patch.object(composition, "_runtime_build_jobs_module", return_value=runtime_build_jobs),
        patch.object(
            composition, "BuildJobApplicationService", side_effect=RuntimeError("service failed")
        ),
        pytest.raises(RuntimeError, match="service failed"),
    ):
        compose_build_job_application(
            system=cast(GraphRAGApplication, object()),
            config=config,
            coordinator=RuntimeOperationCoordinator(),
        )

    assert repository.close_calls == 1
    runtime_build_jobs.FileBuildJobRepository.assert_not_called()
    runtime_build_jobs.BuildJobStoreMigrator.assert_not_called()


def test_worker_composition_closes_repository_when_telemetry_executor_or_runner_fails() -> None:
    config = build_test_config().with_overrides(
        {
            "api": {"build_job_repository_backend": "postgresql"},
            "storage": {"build_job_postgres_dsn": "postgresql://configured.invalid/build_jobs"},
        }
    )
    for failure_point in ("telemetry", "executor", "runner"):
        repository = _ExternalRepository()
        runtime_build_jobs = SimpleNamespace(
            PostgresBuildJobRepository=Mock(return_value=repository),
            BuildJobStoreMigrator=Mock(),
            FileBuildJobRepository=Mock(),
            ExternalBuildJobWorkerRunner=Mock(side_effect=RuntimeError("runner failed")),
        )
        telemetry = Mock()

        with (
            patch.object(
                composition, "_runtime_build_jobs_module", return_value=runtime_build_jobs
            ),
            patch.object(
                composition,
                "get_runtime_telemetry",
                side_effect=RuntimeError("telemetry failed")
                if failure_point == "telemetry"
                else lambda _: telemetry,
            ),
            patch.object(
                composition,
                "_compose_executor",
                side_effect=RuntimeError("executor failed")
                if failure_point == "executor"
                else lambda **_: Mock(),
            ),
            pytest.raises(
                RuntimeError,
                match={
                    "telemetry": "telemetry failed",
                    "executor": "executor failed",
                    "runner": "runner failed",
                }[failure_point],
            ),
        ):
            composition.compose_build_job_worker(
                system=cast(GraphRAGApplication, object()),
                config=config,
                coordinator=RuntimeOperationCoordinator(),
            )

        assert repository.close_calls == (0 if failure_point == "telemetry" else 1)
        runtime_build_jobs.FileBuildJobRepository.assert_not_called()
        runtime_build_jobs.BuildJobStoreMigrator.assert_not_called()


def test_unsupported_backend_defensive_branch_is_bypassed_by_factory() -> None:
    config = SimpleNamespace(
        api=SimpleNamespace(build_job_repository_backend="unsupported"),
        storage=SimpleNamespace(build_job_postgres_dsn=""),
    )
    repository = _ExternalRepository()

    with pytest.raises(ValueError, match=r"^Unsupported build job repository backend\.$"):
        composition._compose_repository(
            runtime_build_jobs=SimpleNamespace(),
            config=cast(object, config),
            repository_factory=None,
        )

    assert (
        composition._compose_repository(
            runtime_build_jobs=SimpleNamespace(),
            config=cast(object, config),
            repository_factory=lambda _: cast(BuildJobRepositoryPort, repository),
        )
        is repository
    )

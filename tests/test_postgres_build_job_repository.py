from __future__ import annotations

import logging
import threading
import unittest
from collections.abc import Callable, Iterator, Mapping
from concurrent.futures import ThreadPoolExecutor
from contextlib import AbstractContextManager, nullcontext
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

import psycopg
import pytest
from psycopg.types.json import Jsonb

from rag_modules.app.build_jobs import (
    BuildJobConcurrentUpdateError,
    BuildJobConflictError,
    BuildJobEvent,
    BuildJobEventListQuery,
    BuildJobEventType,
    BuildJobId,
    BuildJobIdempotencyConflictError,
    BuildJobLease,
    BuildJobLeaseLostError,
    BuildJobListQuery,
    BuildJobNotFoundError,
    BuildJobRepositoryDiagnostics,
    BuildJobRepositoryError,
    BuildJobRepositorySettings,
    BuildJobRepositoryUnavailableError,
    BuildJobSnapshot,
    BuildJobStatus,
    BuildJobSubmissionDisposition,
    BuildJobType,
    JobQueued,
    JobStarted,
    JobSucceeded,
    SubmitBuildJob,
    WorkerIdentity,
    event_to_dict,
)
from rag_modules.runtime.build_jobs.postgres import (
    PostgresBuildJobRepository,
    PostgresBuildJobSchemaManager,
)
from rag_modules.runtime.build_jobs.postgres import repository as repository_module
from rag_modules.runtime.build_jobs.postgres.repository import PostgresBuildJobObservers
from tests.build_job_repository_contract import (
    BuildJobRepositoryContractTests,
    MutableClock,
    submit_and_succeed,
)

pytest_plugins = ("tests.postgres_build_job_helpers",)

NOW = datetime(2026, 7, 26, tzinfo=timezone.utc)
_Now = Callable[[], datetime]


class _Rows:
    def __init__(self, rows: list[tuple[object, ...]], *, rowcount: int = 0) -> None:
        self._rows = rows
        self.rowcount = rowcount

    def fetchone(self) -> tuple[object, ...] | None:
        return self._rows[0] if self._rows else None

    def fetchall(self) -> list[tuple[object, ...]]:
        return list(self._rows)


class _FakeTransaction(AbstractContextManager[None]):
    def __init__(self, connection: _FakeConnection) -> None:
        self._connection = connection

    def __enter__(self) -> None:
        self._connection.transaction_entries += 1
        return None

    def __exit__(self, exc_type, _exc, _traceback) -> bool:
        self._connection.transaction_outcomes.append("rollback" if exc_type else "commit")
        return False


class _FakeConnection:
    def __init__(self, responses: list[_Rows | BaseException]) -> None:
        self._responses = list(responses)
        self.calls: list[tuple[str, object]] = []
        self.transaction_entries = 0
        self.transaction_outcomes: list[str] = []

    def transaction(self) -> _FakeTransaction:
        return _FakeTransaction(self)

    def execute(self, query: object, params: object = None) -> _Rows:
        self.calls.append((str(query), params))
        if not self._responses:
            raise AssertionError("Unexpected database statement.")
        response = self._responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response


class _CommitFailureTransaction(_FakeTransaction):
    def __exit__(self, exc_type, _exc, _traceback) -> bool:
        self._connection.transaction_outcomes.append("rollback")
        if exc_type is None:
            raise _ConnectionFailure("commit failed")
        return False


class _CommitFailureConnection(_FakeConnection):
    def transaction(self) -> _FakeTransaction:
        return _CommitFailureTransaction(self)


class _PoolConnection(AbstractContextManager[_FakeConnection]):
    def __init__(self, connection: _FakeConnection) -> None:
        self._connection = connection

    def __enter__(self) -> _FakeConnection:
        return self._connection

    def __exit__(self, _exc_type, _exc, _traceback) -> bool:
        return False


class _FakePool:
    def __init__(self, connections: list[_FakeConnection] | None = None) -> None:
        self._connections = list(connections or [])
        self.open_calls: list[tuple[bool, float]] = []
        self.checkout_timeouts: list[float | None] = []
        self.close_calls = 0
        self._workers: list[threading.Thread] = []
        self._sched_runner: threading.Thread | None = None

    def open(self, *, wait: bool, timeout: float) -> None:
        self.open_calls.append((wait, timeout))

    def connection(self, timeout: float | None = None) -> _PoolConnection:
        self.checkout_timeouts.append(timeout)
        if not self._connections:
            raise AssertionError("Unexpected pool checkout.")
        return _PoolConnection(self._connections.pop(0))

    def close(self) -> None:
        self.close_calls += 1


class _LoggingFailurePool(_FakePool):
    def __init__(self, *, fail_open: bool) -> None:
        super().__init__()
        self.fail_open = fail_open
        self.name = ""

    def open(self, *, wait: bool, timeout: float) -> None:
        super().open(wait=wait, timeout=timeout)
        if self.fail_open:
            self.emit_connection_failure("pool-open-raw-secret")
            raise _ConnectionFailure("pool-open-final-secret")

    def emit_connection_failure(self, detail: str) -> None:
        logging.getLogger("psycopg.pool").warning(
            "error connecting in %r: %s",
            self.name,
            _ConnectionFailure(f"{detail} dsn=postgresql://user:dsn-secret@unit-test.invalid/jobs"),
        )


class _HungConnectionFailurePool(_LoggingFailurePool):
    def __init__(self) -> None:
        super().__init__(fail_open=False)
        self._release_connection = threading.Event()
        self._failure_logged = threading.Event()
        self.worker = threading.Thread(
            target=self._connect_until_released,
            name="hung-pool-connect",
            daemon=True,
        )

    def open(self, *, wait: bool, timeout: float) -> None:
        _FakePool.open(self, wait=wait, timeout=timeout)
        self._workers = [self.worker]
        self.worker.start()
        raise _ConnectionFailure("pool initialization wait timed out")

    def release_and_wait(self) -> None:
        self._release_connection.set()
        assert self._failure_logged.wait(timeout=2.0)
        self.worker.join(timeout=2.0)

    def _connect_until_released(self) -> None:
        self._release_connection.wait()
        self.emit_connection_failure("hung-connect-late-raw-secret")
        self._failure_logged.set()


class _ExplodingWorkerList(list[threading.Thread]):
    def __iter__(self) -> Iterator[threading.Thread]:
        raise OSError("worker iteration is unavailable")


class _PrivateWorkerStateFailurePool(_LoggingFailurePool):
    def __init__(self) -> None:
        self.worker_state_failure: str | None = None
        super().__init__(fail_open=False)

    def __getattribute__(self, name: str):
        failure = object.__getattribute__(self, "worker_state_failure")
        if name == "_sched_runner" and failure == "scheduler_access":
            raise OSError("scheduler state is unavailable")
        return super().__getattribute__(name)

    def fail_worker_state_capture(self, failure: str) -> None:
        self.worker_state_failure = failure
        if failure == "worker_iteration":
            self._workers = _ExplodingWorkerList()


class _IsAliveFailureThread(threading.Thread):
    def is_alive(self) -> bool:
        raise OSError("worker liveness is unavailable")


class _NamedUniqueViolation(psycopg.errors.UniqueViolation):
    def __init__(self, constraint_name: str) -> None:
        super().__init__("raw-unique-violation-secret")
        self._constraint_name = constraint_name

    @property
    def diag(self) -> SimpleNamespace:
        return SimpleNamespace(constraint_name=self._constraint_name)


class _ConnectionFailure(psycopg.OperationalError):
    sqlstate = "08006"


def _make_repository(
    pool: _FakePool,
    *,
    dsn: str = "postgresql://user:dsn-secret@unit-test.invalid/jobs",
    now: _Now = lambda: NOW,
    settings: BuildJobRepositorySettings | None = None,
) -> PostgresBuildJobRepository:
    schema_manager = SimpleNamespace(verify=lambda: None)
    with (
        patch.object(repository_module, "ConnectionPool", return_value=pool),
        patch.object(
            repository_module,
            "PostgresBuildJobSchemaManager",
            return_value=schema_manager,
        ),
    ):
        return PostgresBuildJobRepository(
            dsn,
            now=now,
            settings=settings or BuildJobRepositorySettings(),
            pool_min_size=1,
            pool_max_size=4,
            pool_timeout_seconds=2.5,
        )


def _make_logging_repository(
    pool: _LoggingFailurePool,
) -> PostgresBuildJobRepository:
    def build_pool(**kwargs):
        pool.name = str(kwargs.get("name") or "")
        return pool

    schema_manager = SimpleNamespace(verify=lambda: None)
    with (
        patch.object(repository_module, "ConnectionPool", side_effect=build_pool),
        patch.object(
            repository_module,
            "PostgresBuildJobSchemaManager",
            return_value=schema_manager,
        ),
    ):
        return PostgresBuildJobRepository(
            "postgresql://user:dsn-secret@unit-test.invalid/jobs",
            now=lambda: NOW,
            settings=BuildJobRepositorySettings(),
            pool_min_size=1,
            pool_max_size=2,
            pool_timeout_seconds=1.0,
        )


def _snapshot(
    character: str = "a",
    *,
    created_at: datetime = NOW,
    status: BuildJobStatus = BuildJobStatus.FAILED,
) -> BuildJobSnapshot:
    return BuildJobSnapshot(
        job_id=BuildJobId(character * 32),
        request_id=f"request-{character}",
        job_type=BuildJobType.REBUILD,
        status=status,
        revision=3,
        created_at=created_at,
        started_at=created_at + timedelta(seconds=1),
        finished_at=created_at + timedelta(seconds=2),
        message="Build failed.",
        error={"code": "BUILD_FAILED", "request_id": f"request-{character}"},
        logs=("Build progress updated.", "Build failed."),
        result={"message": "safe", "nested": {"count": 1}},
        retry_of_job_id=BuildJobId("f" * 32),
        idempotency_key_hash=character * 64,
        worker=WorkerIdentity(f"worker-{character}", "external_worker"),
        lease_token=f"lease-{character}",
        lease_expires_at=created_at + timedelta(seconds=30),
    )


def _snapshot_row(
    snapshot: BuildJobSnapshot,
    *,
    archived_at: datetime | None = None,
    import_source_schema_version: int | None = None,
) -> tuple[object, ...]:
    worker = snapshot.worker
    return (
        str(snapshot.job_id),
        snapshot.request_id,
        snapshot.job_type.value,
        snapshot.status.value,
        snapshot.revision,
        snapshot.created_at,
        snapshot.started_at,
        snapshot.finished_at,
        snapshot.message,
        dict(snapshot.error) if snapshot.error is not None else None,
        list(snapshot.logs),
        dict(snapshot.result) if snapshot.result is not None else None,
        str(snapshot.retry_of_job_id) if snapshot.retry_of_job_id is not None else None,
        snapshot.idempotency_key_hash,
        worker.worker_id if worker is not None else None,
        worker.runner_backend if worker is not None else None,
        snapshot.lease_token,
        snapshot.lease_expires_at,
        archived_at,
        import_source_schema_version,
    )


def _queued_event(snapshot: BuildJobSnapshot, revision: int = 1) -> BuildJobEvent:
    return BuildJobEvent(
        event_id=f"{snapshot.job_id}:{revision}",
        job_id=snapshot.job_id,
        revision=revision,
        event_type=BuildJobEventType.QUEUED,
        schema_version=1,
        occurred_at=snapshot.created_at,
        request_id=snapshot.request_id,
        payload=JobQueued(
            job_type=snapshot.job_type,
            idempotency_key_hash=snapshot.idempotency_key_hash,
            retry_of_job_id=snapshot.retry_of_job_id,
        ),
    )


def _queued_snapshot(
    character: str = "a",
    *,
    created_at: datetime = NOW,
    idempotency_key_hash: str = "",
) -> BuildJobSnapshot:
    return BuildJobSnapshot(
        job_id=BuildJobId(character * 32),
        request_id=f"request-{character}",
        job_type=BuildJobType.BUILD,
        status=BuildJobStatus.QUEUED,
        revision=1,
        created_at=created_at,
        idempotency_key_hash=idempotency_key_hash,
    )


def _started_event(snapshot: BuildJobSnapshot, worker: WorkerIdentity) -> BuildJobEvent:
    return BuildJobEvent(
        event_id=f"{snapshot.job_id}:{snapshot.revision + 1}",
        job_id=snapshot.job_id,
        revision=snapshot.revision + 1,
        event_type=BuildJobEventType.STARTED,
        schema_version=1,
        occurred_at=NOW,
        request_id=snapshot.request_id,
        payload=JobStarted(worker),
    )


def _event_row(event: BuildJobEvent) -> tuple[object, ...]:
    payload = event_to_dict(event)
    return (
        event.event_id,
        str(event.job_id),
        event.revision,
        event.event_type.value,
        event.schema_version,
        event.occurred_at,
        event.request_id,
        payload["payload"],
    )


def test_pool_lifecycle_opens_explicitly_verifies_schema_and_closes_once() -> None:
    pool = _FakePool()
    schema_manager = SimpleNamespace(verify=unittest.mock.Mock())
    with (
        patch.object(repository_module, "ConnectionPool", return_value=pool) as pool_class,
        patch.object(
            repository_module,
            "PostgresBuildJobSchemaManager",
            return_value=schema_manager,
        ) as schema_class,
    ):
        repository = PostgresBuildJobRepository(
            "postgresql://user:private@unit-test.invalid/jobs",
            now=lambda: NOW,
            settings=BuildJobRepositorySettings(),
            pool_min_size=2,
            pool_max_size=6,
            pool_timeout_seconds=3.5,
        )

    pool_arguments = dict(pool_class.call_args.kwargs)
    pool_name = pool_arguments.pop("name")
    assert isinstance(pool_name, str)
    assert pool_name.startswith("build-job-")
    assert pool_arguments == {
        "conninfo": "postgresql://user:private@unit-test.invalid/jobs",
        "min_size": 2,
        "max_size": 6,
        "open": False,
        "timeout": 3.5,
    }
    assert pool.open_calls == [(True, 3.5)]
    schema_class.assert_called_once_with("postgresql://user:private@unit-test.invalid/jobs")
    schema_manager.verify.assert_called_once_with()

    repository.close()
    repository.close()

    assert pool.close_calls == 1


def test_pool_open_failure_sanitizes_dependency_logger_and_retains_fail_safe_protection(
    caplog: pytest.LogCaptureFixture,
) -> None:
    pool = _LoggingFailurePool(fail_open=True)

    def build_pool(**kwargs):
        pool.name = str(kwargs.get("name") or "")
        return pool

    caplog.set_level(logging.WARNING, logger="psycopg.pool")
    with (
        patch.object(repository_module, "ConnectionPool", side_effect=build_pool),
        pytest.raises(
            BuildJobRepositoryUnavailableError,
            match=r"^Build job repository is unavailable\.$",
        ),
    ):
        PostgresBuildJobRepository(
            "postgresql://user:dsn-secret@unit-test.invalid/jobs",
            now=lambda: NOW,
            settings=BuildJobRepositorySettings(),
            pool_min_size=1,
            pool_max_size=2,
            pool_timeout_seconds=1.0,
        )

    dependency_records = [record for record in caplog.records if record.name == "psycopg.pool"]
    assert len(dependency_records) == 1
    record = dependency_records[0]
    assert record.getMessage() == "Build job PostgreSQL pool connection failed."
    assert getattr(record, "backend") == "postgresql"
    assert getattr(record, "operation") == "pool_connect"
    assert getattr(record, "sqlstate_class") == "08"
    assert "raw-secret" not in repr(record.__dict__)
    assert "dsn-secret" not in repr(record.__dict__)
    assert pool.close_calls == 1

    caplog.clear()
    pool.emit_connection_failure("post-close-still-sensitive")
    assert caplog.records[-1].getMessage() == ("Build job PostgreSQL pool connection failed.")
    assert "post-close-still-sensitive" not in repr(caplog.records[-1].__dict__)


def test_real_pool_worker_open_failure_never_emits_raw_exception(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING, logger="psycopg.pool")
    with (
        patch.object(
            psycopg.Connection,
            "connect",
            side_effect=_ConnectionFailure(
                "actual-worker-raw-secret dsn=postgresql://user:dsn-secret@unit-test.invalid/jobs"
            ),
        ),
        pytest.raises(
            BuildJobRepositoryUnavailableError,
            match=r"^Build job repository is unavailable\.$",
        ),
    ):
        PostgresBuildJobRepository(
            "postgresql://user:dsn-secret@unit-test.invalid/jobs",
            now=lambda: NOW,
            settings=BuildJobRepositorySettings(),
            pool_min_size=1,
            pool_max_size=1,
            pool_timeout_seconds=0.05,
        )

    dependency_records = [record for record in caplog.records if record.name == "psycopg.pool"]
    assert dependency_records
    assert all(
        record.getMessage() == "Build job PostgreSQL pool connection failed."
        for record in dependency_records
    )
    assert all("raw-secret" not in repr(record.__dict__) for record in dependency_records)
    assert all("dsn-secret" not in repr(record.__dict__) for record in dependency_records)


def test_hung_connect_failure_after_close_timeout_remains_sanitized(
    caplog: pytest.LogCaptureFixture,
) -> None:
    pool = _HungConnectionFailurePool()

    def build_pool(**kwargs):
        pool.name = str(kwargs.get("name") or "")
        return pool

    caplog.set_level(logging.WARNING, logger="psycopg.pool")
    try:
        with (
            patch.object(repository_module, "ConnectionPool", side_effect=build_pool),
            pytest.raises(
                BuildJobRepositoryUnavailableError,
                match=r"^Build job repository is unavailable\.$",
            ),
        ):
            PostgresBuildJobRepository(
                "postgresql://user:dsn-secret@unit-test.invalid/jobs",
                now=lambda: NOW,
                settings=BuildJobRepositorySettings(),
                pool_min_size=1,
                pool_max_size=1,
                pool_timeout_seconds=0.05,
            )
    finally:
        pool.release_and_wait()

    dependency_records = [record for record in caplog.records if record.name == "psycopg.pool"]
    assert dependency_records[-1].getMessage() == ("Build job PostgreSQL pool connection failed.")
    assert "hung-connect-late-raw-secret" not in repr(dependency_records[-1].__dict__)
    assert "dsn-secret" not in repr(dependency_records[-1].__dict__)


def test_runtime_pool_replenishment_sanitizes_only_this_repository_pool(
    caplog: pytest.LogCaptureFixture,
) -> None:
    pool = _LoggingFailurePool(fail_open=False)

    def build_pool(**kwargs):
        pool.name = str(kwargs.get("name") or "")
        return pool

    schema_manager = SimpleNamespace(verify=lambda: None)
    caplog.set_level(logging.WARNING, logger="psycopg.pool")
    with (
        patch.object(repository_module, "ConnectionPool", side_effect=build_pool),
        patch.object(
            repository_module,
            "PostgresBuildJobSchemaManager",
            return_value=schema_manager,
        ),
    ):
        repository = PostgresBuildJobRepository(
            "postgresql://user:dsn-secret@unit-test.invalid/jobs",
            now=lambda: NOW,
            settings=BuildJobRepositorySettings(),
            pool_min_size=1,
            pool_max_size=2,
            pool_timeout_seconds=1.0,
        )

    try:
        pool.emit_connection_failure("runtime-replenishment-raw-secret")
        logging.getLogger("psycopg.pool").warning(
            "error connecting in %r: %s",
            "unrelated-pool",
            "unrelated-detail-visible",
        )
    finally:
        repository.close()

    dependency_records = [record for record in caplog.records if record.name == "psycopg.pool"]
    assert dependency_records[0].getMessage() == ("Build job PostgreSQL pool connection failed.")
    assert "runtime-replenishment-raw-secret" not in repr(dependency_records[0].__dict__)
    assert "dsn-secret" not in repr(dependency_records[0].__dict__)
    assert dependency_records[1].getMessage() == (
        "error connecting in 'unrelated-pool': unrelated-detail-visible"
    )

    caplog.clear()
    pool.emit_connection_failure("post-normal-close-visible")
    assert "post-normal-close-visible" in caplog.records[-1].getMessage()


def test_two_repositories_concurrently_close_and_log_with_one_process_filter(
    caplog: pytest.LogCaptureFixture,
) -> None:
    first_pool = _LoggingFailurePool(fail_open=False)
    second_pool = _LoggingFailurePool(fail_open=False)

    def make_repository(pool: _LoggingFailurePool) -> PostgresBuildJobRepository:
        def build_pool(**kwargs):
            pool.name = str(kwargs.get("name") or "")
            return pool

        schema_manager = SimpleNamespace(verify=lambda: None)
        with (
            patch.object(repository_module, "ConnectionPool", side_effect=build_pool),
            patch.object(
                repository_module,
                "PostgresBuildJobSchemaManager",
                return_value=schema_manager,
            ),
        ):
            return PostgresBuildJobRepository(
                "postgresql://user:dsn-secret@unit-test.invalid/jobs",
                now=lambda: NOW,
                settings=BuildJobRepositorySettings(),
                pool_min_size=1,
                pool_max_size=2,
                pool_timeout_seconds=1.0,
            )

    first_repository = make_repository(first_pool)
    second_repository = make_repository(second_pool)
    caplog.set_level(logging.WARNING, logger="psycopg.pool")
    caplog.clear()
    try:
        process_filters = [
            item
            for item in logging.getLogger("psycopg.pool").filters
            if isinstance(item, repository_module._PoolConnectionLogSanitizer)
        ]
        assert len(process_filters) == 1

        start = threading.Barrier(2)

        def close_first() -> None:
            start.wait()
            first_repository.close()

        def log_from_second() -> None:
            start.wait()
            for index in range(100):
                second_pool.emit_connection_failure(f"concurrent-raw-secret-{index}")

        with ThreadPoolExecutor(max_workers=2) as executor:
            close_future = executor.submit(close_first)
            log_future = executor.submit(log_from_second)
            close_future.result()
            log_future.result()

        second_pool.emit_connection_failure("after-first-close-raw-secret")
    finally:
        first_repository.close()
        second_repository.close()

    dependency_records = [record for record in caplog.records if record.name == "psycopg.pool"]
    assert len(dependency_records) == 101
    assert all(
        record.getMessage() == "Build job PostgreSQL pool connection failed."
        for record in dependency_records
    )
    assert all("raw-secret" not in repr(record.__dict__) for record in dependency_records)
    assert all("dsn-secret" not in repr(record.__dict__) for record in dependency_records)


@pytest.mark.parametrize("failure", ["scheduler_access", "worker_iteration"])
def test_close_still_closes_and_retains_protection_when_worker_capture_fails(
    failure: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    pool = _PrivateWorkerStateFailurePool()
    repository = _make_logging_repository(pool)
    pool.fail_worker_state_capture(failure)
    caplog.set_level(logging.WARNING, logger="psycopg.pool")

    repository.close()

    assert pool.close_calls == 1
    pool.emit_connection_failure(f"{failure}-raw-secret")
    record = caplog.records[-1]
    assert record.getMessage() == "Build job PostgreSQL pool connection failed."
    assert f"{failure}-raw-secret" not in repr(record.__dict__)


def test_close_retains_protection_when_worker_liveness_check_fails(
    caplog: pytest.LogCaptureFixture,
) -> None:
    pool = _LoggingFailurePool(fail_open=False)
    pool._workers = [_IsAliveFailureThread()]
    repository = _make_logging_repository(pool)
    caplog.set_level(logging.WARNING, logger="psycopg.pool")

    repository.close()

    assert pool.close_calls == 1
    pool.emit_connection_failure("is-alive-raw-secret")
    record = caplog.records[-1]
    assert record.getMessage() == "Build job PostgreSQL pool connection failed."
    assert "is-alive-raw-secret" not in repr(record.__dict__)


def test_schema_verification_failure_closes_the_open_pool() -> None:
    pool = _FakePool()
    schema_manager = SimpleNamespace(
        verify=unittest.mock.Mock(
            side_effect=BuildJobRepositoryError("Build job PostgreSQL schema is not ready.")
        )
    )
    with (
        patch.object(repository_module, "ConnectionPool", return_value=pool),
        patch.object(
            repository_module,
            "PostgresBuildJobSchemaManager",
            return_value=schema_manager,
        ),
        pytest.raises(
            BuildJobRepositoryError,
            match=r"^Build job PostgreSQL schema is not ready\.$",
        ),
    ):
        PostgresBuildJobRepository(
            "postgresql://user:private@unit-test.invalid/jobs",
            now=lambda: NOW,
            settings=BuildJobRepositorySettings(),
            pool_min_size=1,
            pool_max_size=2,
            pool_timeout_seconds=1.0,
        )

    assert pool.close_calls == 1


def test_schema_verification_failure_is_not_masked_by_worker_capture_failure(
    caplog: pytest.LogCaptureFixture,
) -> None:
    pool = _PrivateWorkerStateFailurePool()
    pool.fail_worker_state_capture("scheduler_access")
    schema_manager = SimpleNamespace(
        verify=unittest.mock.Mock(
            side_effect=BuildJobRepositoryError("Build job PostgreSQL schema is not ready.")
        )
    )

    def build_pool(**kwargs):
        pool.name = str(kwargs.get("name") or "")
        return pool

    caplog.set_level(logging.WARNING, logger="psycopg.pool")
    with (
        patch.object(repository_module, "ConnectionPool", side_effect=build_pool),
        patch.object(
            repository_module,
            "PostgresBuildJobSchemaManager",
            return_value=schema_manager,
        ),
        pytest.raises(
            BuildJobRepositoryError,
            match=r"^Build job PostgreSQL schema is not ready\.$",
        ),
    ):
        PostgresBuildJobRepository(
            "postgresql://user:dsn-secret@unit-test.invalid/jobs",
            now=lambda: NOW,
            settings=BuildJobRepositorySettings(),
            pool_min_size=1,
            pool_max_size=2,
            pool_timeout_seconds=1.0,
        )

    assert pool.close_calls == 1
    pool.emit_connection_failure("schema-close-raw-secret")
    record = caplog.records[-1]
    assert record.getMessage() == "Build job PostgreSQL pool connection failed."
    assert "schema-close-raw-secret" not in repr(record.__dict__)


def test_unexpected_schema_verification_failure_is_sanitized(
    caplog: pytest.LogCaptureFixture,
) -> None:
    pool = _FakePool()
    schema_manager = SimpleNamespace(
        verify=unittest.mock.Mock(side_effect=RuntimeError("raw-schema-secret"))
    )
    caplog.set_level(logging.ERROR, logger=repository_module.__name__)

    with (
        patch.object(repository_module, "ConnectionPool", return_value=pool),
        patch.object(
            repository_module,
            "PostgresBuildJobSchemaManager",
            return_value=schema_manager,
        ),
        pytest.raises(
            BuildJobRepositoryUnavailableError,
            match=r"^Build job repository is unavailable\.$",
        ),
    ):
        PostgresBuildJobRepository(
            "postgresql://user:dsn-secret@unit-test.invalid/jobs",
            now=lambda: NOW,
            settings=BuildJobRepositorySettings(),
            pool_min_size=1,
            pool_max_size=2,
            pool_timeout_seconds=1.0,
        )

    assert pool.close_calls == 1
    assert len(caplog.records) == 1
    record = caplog.records[0]
    assert record.getMessage() == "Build job PostgreSQL repository operation failed."
    assert getattr(record, "operation") == "verify_schema"
    assert getattr(record, "sqlstate_class") == "XX"
    assert "dsn-secret" not in caplog.text
    assert "raw-schema-secret" not in caplog.text


def test_submission_writes_projection_and_event_in_one_transaction_with_adapted_json() -> None:
    connection = _FakeConnection([_Rows([]), _Rows([]), _Rows([]), _Rows([]), _Rows([])])
    repository = _make_repository(_FakePool([connection]))
    command = SubmitBuildJob(
        job_id=BuildJobId("a" * 32),
        request_id="parameter-secret",
        job_type=BuildJobType.BUILD,
        idempotency_key="raw-idempotency-secret",
    )

    submission = repository.submit(command)

    assert submission.disposition is BuildJobSubmissionDisposition.CREATED
    assert submission.snapshot.job_id == command.job_id
    assert connection.transaction_entries == 1
    assert connection.transaction_outcomes == ["commit"]
    assert len(connection.calls) == 5
    assert all("OFFSET" not in statement.upper() for statement, _params in connection.calls)
    projection_parameters = connection.calls[1][1]
    event_parameters = connection.calls[2][1]
    assert isinstance(projection_parameters, tuple)
    assert isinstance(event_parameters, tuple)
    assert projection_parameters[9] is None
    assert isinstance(projection_parameters[10], Jsonb)
    assert projection_parameters[11] is None
    assert isinstance(event_parameters[-1], Jsonb)
    assert "ROW_NUMBER() OVER" in connection.calls[3][0]
    assert "archived_at <= %(cutoff)s" in connection.calls[4][0]
    assert "raw-idempotency-secret" not in repr(connection.calls)


def test_idempotency_named_constraint_race_replays_owner_in_a_new_transaction() -> None:
    owner = _snapshot("b", status=BuildJobStatus.QUEUED)
    first = _FakeConnection(
        [
            _Rows([]),
            _NamedUniqueViolation("build_jobs_idempotency_uq"),
        ]
    )
    replay = _FakeConnection([_Rows([_snapshot_row(owner)])])
    repository = _make_repository(_FakePool([first, replay]))

    submission = repository.submit(
        SubmitBuildJob(
            job_id=BuildJobId("a" * 32),
            request_id="request-a",
            job_type=owner.job_type,
            idempotency_key="stable-race-key",
            retry_of_job_id=owner.retry_of_job_id,
        )
    )

    assert submission.disposition is BuildJobSubmissionDisposition.REPLAYED
    assert submission.snapshot == owner
    assert first.transaction_outcomes == ["rollback"]
    assert replay.transaction_outcomes == ["commit"]


def test_active_named_constraint_race_returns_the_current_active_snapshot() -> None:
    active = _snapshot("c", status=BuildJobStatus.RUNNING)
    first = _FakeConnection(
        [
            _Rows([]),
            _NamedUniqueViolation("build_jobs_one_active_uq"),
        ]
    )
    conflict_read = _FakeConnection([_Rows([_snapshot_row(active)])])
    repository = _make_repository(_FakePool([first, conflict_read]))

    with pytest.raises(BuildJobConflictError) as caught:
        repository.submit(
            SubmitBuildJob(
                job_id=BuildJobId("a" * 32),
                request_id="request-a",
                job_type=BuildJobType.BUILD,
                idempotency_key="different-key",
            )
        )

    assert str(caught.value) == "A build job is already in progress."
    assert caught.value.snapshot == active
    assert first.transaction_outcomes == ["rollback"]
    assert conflict_read.transaction_outcomes == ["commit"]


def test_unclassified_unique_violation_is_not_retried() -> None:
    connection = _FakeConnection(
        [
            _Rows([]),
            _NamedUniqueViolation("unexpected_unique_constraint"),
        ]
    )
    pool = _FakePool([connection])
    repository = _make_repository(pool)

    with pytest.raises(
        BuildJobRepositoryUnavailableError,
        match=r"^Build job repository is unavailable\.$",
    ):
        repository.submit(
            SubmitBuildJob(
                job_id=BuildJobId("a" * 32),
                request_id="request-a",
                job_type=BuildJobType.BUILD,
                idempotency_key="stable-key",
            )
        )

    assert len(pool.checkout_timeouts) == 1
    assert connection.transaction_outcomes == ["rollback"]


def test_idempotency_same_type_replays_when_retry_source_differs() -> None:
    owner = _snapshot("d", status=BuildJobStatus.SUCCEEDED)
    connection = _FakeConnection([_Rows([_snapshot_row(owner)])])
    repository = _make_repository(_FakePool([connection]))

    submission = repository.submit(
        SubmitBuildJob(
            job_id=BuildJobId("a" * 32),
            request_id="different-request-id",
            job_type=owner.job_type,
            idempotency_key="raw-idempotency-secret",
            retry_of_job_id=None,
        )
    )

    assert submission.disposition is BuildJobSubmissionDisposition.REPLAYED
    assert submission.snapshot == owner


def test_idempotency_type_mismatch_raises_a_safe_conflict() -> None:
    owner = _snapshot("d", status=BuildJobStatus.SUCCEEDED)
    connection = _FakeConnection([_Rows([_snapshot_row(owner)])])
    repository = _make_repository(_FakePool([connection]))

    with pytest.raises(BuildJobIdempotencyConflictError) as caught:
        repository.submit(
            SubmitBuildJob(
                job_id=BuildJobId("a" * 32),
                request_id="different-request-id",
                job_type=BuildJobType.BUILD,
                idempotency_key="raw-idempotency-secret",
            )
        )

    assert str(caught.value) == "Idempotency key conflicts with an existing build job."
    assert caught.value.snapshot == owner
    assert "raw-idempotency-secret" not in str(caught.value)
    assert owner.idempotency_key_hash not in str(caught.value)


def test_list_queries_use_opaque_keysets_and_separate_static_status_sql() -> None:
    newest = _snapshot("e", created_at=NOW + timedelta(seconds=1))
    oldest = _snapshot("d", created_at=NOW)
    unfiltered = _FakeConnection([_Rows([_snapshot_row(newest), _snapshot_row(oldest)])])
    filtered = _FakeConnection([_Rows([_snapshot_row(oldest)])])
    pool = _FakePool([unfiltered, filtered])
    repository = _make_repository(
        pool,
        settings=BuildJobRepositorySettings(list_default_limit=1, list_max_limit=1),
    )

    first_page = repository.list_page(BuildJobListQuery(limit=50))
    filtered_page = repository.list_page(BuildJobListQuery(status=BuildJobStatus.FAILED, limit=1))

    assert first_page.jobs == (newest,)
    assert first_page.next_cursor
    assert filtered_page.jobs == (oldest,)
    assert filtered_page.next_cursor == ""
    unfiltered_sql, unfiltered_params = unfiltered.calls[0]
    filtered_sql, filtered_params = filtered.calls[0]
    assert "OFFSET" not in unfiltered_sql.upper()
    assert "(created_at, job_id) <" in unfiltered_sql
    assert "status =" not in unfiltered_sql
    assert "status = %(status)s" in filtered_sql
    assert "OR %(status)" not in filtered_sql
    for statement in (unfiltered_sql, filtered_sql):
        assert "%(cursor_created_at)s::timestamptz IS NULL" in statement
        assert "(%(cursor_created_at)s::timestamptz, %(cursor_job_id)s::text)" in statement
    assert isinstance(unfiltered_params, Mapping)
    assert unfiltered_params == {
        "cursor_created_at": None,
        "cursor_job_id": None,
        "fetch_limit": 2,
    }
    assert filtered_params == {
        "status": BuildJobStatus.FAILED.value,
        "cursor_created_at": None,
        "cursor_job_id": None,
        "fetch_limit": 2,
    }


def test_event_pages_are_revision_ordered_and_invalid_cursor_never_checks_out_connection() -> None:
    snapshot = _snapshot("e")
    first_event = _queued_event(snapshot)
    second_event = BuildJobEvent(
        event_id=f"{snapshot.job_id}:2",
        job_id=snapshot.job_id,
        revision=2,
        event_type=BuildJobEventType.STARTED,
        schema_version=1,
        occurred_at=NOW + timedelta(seconds=1),
        request_id=snapshot.request_id,
        payload=JobStarted(WorkerIdentity("worker-e", "external_worker")),
    )
    first_connection = _FakeConnection(
        [
            _Rows([(True, True)]),
            _Rows([_event_row(first_event), _event_row(second_event)]),
        ]
    )
    second_connection = _FakeConnection(
        [
            _Rows([(True, True)]),
            _Rows([_event_row(second_event)]),
        ]
    )
    pool = _FakePool([first_connection, second_connection])
    repository = _make_repository(
        pool,
        settings=BuildJobRepositorySettings(list_default_limit=1, list_max_limit=1),
    )

    first_page = repository.list_events(
        snapshot.job_id,
        BuildJobEventListQuery(limit=50),
    )
    second_page = repository.list_events(
        snapshot.job_id,
        BuildJobEventListQuery(limit=50, cursor=first_page.next_cursor),
    )

    assert first_page.events == (first_event,)
    assert first_page.next_cursor
    assert second_page.events == (second_event,)
    assert second_page.next_cursor == ""
    subject_sql, subject_params = first_connection.calls[0]
    assert "FROM graph_rag_control_plane.build_jobs" in subject_sql
    assert "FOR UPDATE" in subject_sql
    assert subject_params == {"job_id": str(snapshot.job_id)}
    event_sql, event_params = first_connection.calls[1]
    assert "revision > %(cursor_revision)s" in event_sql
    assert "ORDER BY revision" in event_sql
    assert "OFFSET" not in event_sql.upper()
    assert event_params == {
        "job_id": str(snapshot.job_id),
        "cursor_revision": -1,
        "fetch_limit": 2,
    }
    checkout_count = len(pool.checkout_timeouts)
    with pytest.raises(ValueError, match=r"^invalid build job event cursor$"):
        repository.list_events(
            snapshot.job_id,
            BuildJobEventListQuery(cursor="not-valid"),
        )
    assert len(pool.checkout_timeouts) == checkout_count


def test_existing_job_without_events_is_reported_as_safe_repository_corruption() -> None:
    snapshot = _snapshot("f")
    connection = _FakeConnection([_Rows([(True, False)])])
    repository = _make_repository(_FakePool([connection]))

    with pytest.raises(
        BuildJobRepositoryUnavailableError,
        match=r"^Build job repository is unavailable\.$",
    ):
        repository.list_events(snapshot.job_id, BuildJobEventListQuery())


def test_malformed_baseline_payload_is_reported_as_safe_repository_unavailable() -> None:
    snapshot = _snapshot("f")
    malformed_event_row = (
        f"{snapshot.job_id}:baseline:0",
        str(snapshot.job_id),
        0,
        "baseline_imported",
        1,
        NOW,
        snapshot.request_id,
        {"source_schema_version": 999},
    )
    connection = _FakeConnection(
        [
            _Rows([(True, True)]),
            _Rows([malformed_event_row]),
        ]
    )
    repository = _make_repository(_FakePool([connection]))

    with pytest.raises(
        BuildJobRepositoryUnavailableError,
        match=r"^Build job repository is unavailable\.$",
    ):
        repository.list_events(snapshot.job_id, BuildJobEventListQuery())

    assert connection.transaction_outcomes == ["rollback"]


def test_missing_event_subject_raises_not_found() -> None:
    job_id = BuildJobId("f" * 32)
    connection = _FakeConnection([_Rows([])])
    repository = _make_repository(_FakePool([connection]))

    with pytest.raises(BuildJobNotFoundError) as caught:
        repository.list_events(job_id, BuildJobEventListQuery())

    assert caught.value.job_id == job_id


def test_database_failure_logs_only_safe_structured_diagnostics(
    caplog: pytest.LogCaptureFixture,
) -> None:
    connection = _FakeConnection(
        [
            _Rows([]),
            _Rows([]),
            _ConnectionFailure("raw-exception-secret"),
        ]
    )
    repository = _make_repository(_FakePool([connection]))
    caplog.set_level(logging.ERROR, logger=repository_module.__name__)

    with pytest.raises(
        BuildJobRepositoryUnavailableError,
        match=r"^Build job repository is unavailable\.$",
    ):
        repository.submit(
            SubmitBuildJob(
                job_id=BuildJobId("a" * 32),
                request_id="parameter-secret",
                job_type=BuildJobType.BUILD,
                idempotency_key="raw-idempotency-secret",
            )
        )

    assert connection.transaction_outcomes == ["rollback"]
    assert len(caplog.records) == 1
    record = caplog.records[0]
    assert record.getMessage() == "Build job PostgreSQL repository operation failed."
    assert record.backend == "postgresql"
    assert record.operation == "submit"
    assert record.sqlstate_class == "08"
    rendered = caplog.text
    assert "dsn-secret" not in rendered
    assert "parameter-secret" not in rendered
    assert "raw-idempotency-secret" not in rendered
    assert "raw-exception-secret" not in rendered
    assert "INSERT" not in rendered


def test_claim_next_locks_oldest_queued_row_and_writes_event_and_projection_atomically() -> None:
    queued = _queued_snapshot("a")
    connection = _FakeConnection([_Rows([_snapshot_row(queued)]), _Rows([]), _Rows([])])
    repository = _make_repository(
        _FakePool([connection]),
        settings=BuildJobRepositorySettings(lease_seconds=30),
    )
    worker = WorkerIdentity("worker-a", "external_worker")

    lease = repository.claim_next(worker)

    assert lease is not None
    assert lease.job_id == queued.job_id
    assert lease.revision == 2
    assert lease.worker == worker
    assert lease.lease_token
    assert lease.lease_expires_at == NOW + timedelta(seconds=30)
    assert connection.transaction_outcomes == ["commit"]
    assert len(connection.calls) == 3
    claim_sql, _claim_params = connection.calls[0]
    assert "FOR UPDATE SKIP LOCKED" in claim_sql
    assert "ORDER BY created_at, job_id" in claim_sql
    assert "status = 'queued'" in claim_sql
    assert connection.calls[1][0] == repository_module._INSERT_EVENT_SQL
    assert "UPDATE graph_rag_control_plane.build_jobs" in connection.calls[2][0]


def test_claim_next_returns_none_without_writing_when_no_job_is_dispatchable() -> None:
    connection = _FakeConnection([_Rows([])])
    repository = _make_repository(_FakePool([connection]))

    assert repository.claim_next(WorkerIdentity("worker-a", "in_process")) is None
    assert len(connection.calls) == 1
    assert connection.transaction_outcomes == ["commit"]


@pytest.mark.parametrize(
    "lease_mutation",
    [
        lambda lease: replace(lease, revision=lease.revision - 1),
        lambda lease: replace(lease, worker=WorkerIdentity("wrong-worker", "in_process")),
        lambda lease: replace(lease, worker=WorkerIdentity("worker-a", "wrong-backend")),
        lambda lease: replace(lease, lease_token="wrong-token"),
    ],
)
def test_renew_lease_rejects_stale_revision_owner_or_token(lease_mutation) -> None:
    worker = WorkerIdentity("worker-a", "in_process")
    claimed = replace(
        _queued_snapshot("a"),
        status=BuildJobStatus.CLAIMED,
        revision=2,
        worker=worker,
        lease_token="correct-token",
        lease_expires_at=NOW + timedelta(seconds=30),
    )
    lease = BuildJobLease(
        job_id=claimed.job_id,
        revision=claimed.revision,
        worker=worker,
        lease_token=claimed.lease_token,
        lease_expires_at=claimed.lease_expires_at,
    )
    connection = _FakeConnection([_Rows([_snapshot_row(claimed)])])
    repository = _make_repository(_FakePool([connection]))

    with pytest.raises(
        BuildJobLeaseLostError,
        match=r"^Build job lease is no longer owned by this worker\.$",
    ):
        repository.renew_lease(lease_mutation(lease))

    assert len(connection.calls) == 1
    assert "FOR UPDATE" in connection.calls[0][0]
    assert connection.transaction_outcomes == ["rollback"]


def test_renew_lease_treats_expiry_equal_to_now_as_lost() -> None:
    worker = WorkerIdentity("worker-a", "in_process")
    claimed = replace(
        _queued_snapshot("a"),
        status=BuildJobStatus.CLAIMED,
        revision=2,
        worker=worker,
        lease_token="correct-token",
        lease_expires_at=NOW,
    )
    lease = BuildJobLease(
        job_id=claimed.job_id,
        revision=claimed.revision,
        worker=worker,
        lease_token=claimed.lease_token,
        lease_expires_at=NOW,
    )
    connection = _FakeConnection([_Rows([_snapshot_row(claimed)])])
    repository = _make_repository(_FakePool([connection]))

    with pytest.raises(BuildJobLeaseLostError):
        repository.renew_lease(lease)

    assert len(connection.calls) == 1
    assert connection.transaction_outcomes == ["rollback"]


def test_renew_lease_updates_only_expiry_and_updated_at() -> None:
    clock = MutableClock(NOW)
    worker = WorkerIdentity("worker-a", "in_process")
    claimed = replace(
        _queued_snapshot("a"),
        status=BuildJobStatus.CLAIMED,
        revision=2,
        worker=worker,
        lease_token="correct-token",
        lease_expires_at=NOW + timedelta(seconds=30),
    )
    lease = BuildJobLease(
        job_id=claimed.job_id,
        revision=claimed.revision,
        worker=worker,
        lease_token=claimed.lease_token,
        lease_expires_at=claimed.lease_expires_at,
    )
    connection = _FakeConnection([_Rows([_snapshot_row(claimed)]), _Rows([])])
    repository = _make_repository(
        _FakePool([connection]),
        now=clock.now,
        settings=BuildJobRepositorySettings(lease_seconds=30),
    )
    clock.advance(seconds=5)

    renewed = repository.renew_lease(lease)

    assert renewed == replace(lease, lease_expires_at=NOW + timedelta(seconds=35))
    update_sql, update_params = connection.calls[1]
    assert "SET lease_expires_at = %(lease_expires_at)s" in update_sql
    assert "updated_at = %(updated_at)s" in update_sql
    assert "revision =" not in update_sql
    assert update_params == {
        "job_id": str(claimed.job_id),
        "lease_expires_at": renewed.lease_expires_at,
        "updated_at": NOW + timedelta(seconds=5),
    }
    assert connection.transaction_outcomes == ["commit"]


def test_apply_rejects_stale_revision_before_writing() -> None:
    worker = WorkerIdentity("worker-a", "in_process")
    claimed = replace(
        _queued_snapshot("a"),
        status=BuildJobStatus.CLAIMED,
        revision=2,
        worker=worker,
        lease_token="correct-token",
        lease_expires_at=NOW + timedelta(seconds=30),
    )
    connection = _FakeConnection([_Rows([_snapshot_row(claimed)])])
    repository = _make_repository(_FakePool([connection]))

    with pytest.raises(BuildJobConcurrentUpdateError, match=r"^Expected revision 1, found 2\.$"):
        repository.apply(
            _started_event(claimed, worker),
            expected_revision=1,
        )

    assert len(connection.calls) == 1
    assert connection.transaction_outcomes == ["rollback"]


@pytest.mark.parametrize(
    "lease_mutation",
    [
        lambda lease: replace(lease, revision=lease.revision - 1),
        lambda lease: replace(lease, worker=WorkerIdentity("wrong-worker", "in_process")),
        lambda lease: replace(lease, lease_token="wrong-token"),
    ],
)
def test_apply_rejects_stale_lease_revision_owner_or_token(lease_mutation) -> None:
    worker = WorkerIdentity("worker-a", "in_process")
    claimed = replace(
        _queued_snapshot("a"),
        status=BuildJobStatus.CLAIMED,
        revision=2,
        worker=worker,
        lease_token="correct-token",
        lease_expires_at=NOW + timedelta(seconds=30),
    )
    lease = BuildJobLease(
        job_id=claimed.job_id,
        revision=claimed.revision,
        worker=worker,
        lease_token=claimed.lease_token,
        lease_expires_at=claimed.lease_expires_at,
    )
    connection = _FakeConnection([_Rows([_snapshot_row(claimed)])])
    repository = _make_repository(_FakePool([connection]))

    with pytest.raises(BuildJobLeaseLostError):
        repository.apply(
            _started_event(claimed, worker),
            expected_revision=claimed.revision,
            lease=lease_mutation(lease),
        )

    assert len(connection.calls) == 1
    assert connection.transaction_outcomes == ["rollback"]


def test_apply_rolls_back_inserted_event_when_projection_update_fails() -> None:
    worker = WorkerIdentity("worker-a", "in_process")
    claimed = replace(
        _queued_snapshot("a"),
        status=BuildJobStatus.CLAIMED,
        revision=2,
        worker=worker,
        lease_token="correct-token",
        lease_expires_at=NOW + timedelta(seconds=30),
    )
    lease = BuildJobLease(
        job_id=claimed.job_id,
        revision=claimed.revision,
        worker=worker,
        lease_token=claimed.lease_token,
        lease_expires_at=claimed.lease_expires_at,
    )
    connection = _FakeConnection(
        [
            _Rows([_snapshot_row(claimed)]),
            _Rows([]),
            _ConnectionFailure("forced projection update failure"),
        ]
    )
    repository = _make_repository(_FakePool([connection]))

    with pytest.raises(BuildJobRepositoryUnavailableError):
        repository.apply(
            _started_event(claimed, worker),
            expected_revision=claimed.revision,
            lease=lease,
        )

    assert connection.calls[1][0] == repository_module._INSERT_EVENT_SQL
    assert "UPDATE graph_rag_control_plane.build_jobs" in connection.calls[2][0]
    assert connection.transaction_outcomes == ["rollback"]


def test_terminal_apply_clears_lease_and_runs_retention_in_the_same_transaction() -> None:
    worker = WorkerIdentity("worker-a", "in_process")
    running = replace(
        _queued_snapshot("a"),
        status=BuildJobStatus.RUNNING,
        revision=3,
        started_at=NOW,
        worker=worker,
        lease_token="correct-token",
        lease_expires_at=NOW + timedelta(seconds=30),
    )
    lease = BuildJobLease(
        job_id=running.job_id,
        revision=running.revision,
        worker=worker,
        lease_token=running.lease_token,
        lease_expires_at=running.lease_expires_at,
    )
    event = BuildJobEvent(
        event_id=f"{running.job_id}:4",
        job_id=running.job_id,
        revision=4,
        event_type=BuildJobEventType.SUCCEEDED,
        schema_version=1,
        occurred_at=NOW,
        request_id=running.request_id,
        payload=JobSucceeded(result={"message": "Knowledge base build completed."}),
    )
    connection = _FakeConnection(
        [
            _Rows([_snapshot_row(running)]),
            _Rows([]),
            _Rows([]),
            _Rows([]),
            _Rows([]),
        ]
    )
    pool = _FakePool([connection])
    repository = _make_repository(pool)

    updated = repository.apply(
        event,
        expected_revision=running.revision,
        lease=lease,
    )

    assert updated.status is BuildJobStatus.SUCCEEDED
    assert updated.lease_token == ""
    assert updated.lease_expires_at is None
    assert len(pool.checkout_timeouts) == 1
    assert connection.transaction_outcomes == ["commit"]
    projection_params = connection.calls[2][1]
    assert isinstance(projection_params, Mapping)
    assert projection_params["lease_token"] == ""
    assert projection_params["lease_expires_at"] is None
    assert "ROW_NUMBER() OVER" in connection.calls[3][0]
    assert "archived_at <= %(cutoff)s" in connection.calls[4][0]


def test_find_dispatchable_is_bounded_and_oldest_first() -> None:
    first = _queued_snapshot("a", created_at=NOW)
    second = _queued_snapshot("b", created_at=NOW + timedelta(seconds=1))
    connection = _FakeConnection([_Rows([(str(first.job_id),), (str(second.job_id),)])])
    repository = _make_repository(_FakePool([connection]))

    assert repository.find_dispatchable(limit=2) == (first.job_id, second.job_id)
    sql, params = connection.calls[0]
    assert "archived_at IS NULL" in sql
    assert "status = 'queued'" in sql
    assert "ORDER BY created_at, job_id" in sql
    assert params == {"limit": 2}
    assert repository.find_dispatchable(limit=0) == ()


def test_recovery_selects_expiry_inclusively_and_persists_interruption_atomically() -> None:
    worker = WorkerIdentity("worker-a", "in_process")
    expired = replace(
        _queued_snapshot("a"),
        status=BuildJobStatus.CLAIMED,
        revision=2,
        worker=worker,
        lease_token="correct-token",
        lease_expires_at=NOW,
    )
    connection = _FakeConnection(
        [
            _Rows([_snapshot_row(expired)]),
            _Rows([]),
            _Rows([]),
            _Rows([]),
            _Rows([]),
            _Rows([]),
            _Rows([]),
            _Rows([]),
        ]
    )
    repository = _make_repository(_FakePool([connection]))

    recovered = repository.recover_expired_leases()

    assert len(recovered) == 1
    assert recovered[0].status is BuildJobStatus.INTERRUPTED
    assert recovered[0].revision == 3
    recovery_sql, recovery_params = connection.calls[0]
    assert "lease_expires_at <= %(now)s" in recovery_sql
    assert "FOR UPDATE SKIP LOCKED" in recovery_sql
    assert recovery_params == {"now": NOW, "limit": 100}
    assert connection.calls[1][0] == repository_module._INSERT_EVENT_SQL
    assert "UPDATE graph_rag_control_plane.build_jobs" in connection.calls[2][0]
    assert connection.transaction_outcomes == ["commit"]


@pytest.mark.parametrize(
    "snapshot_mutation",
    [
        lambda snapshot: replace(snapshot, worker=None),
        lambda snapshot: replace(snapshot, lease_token=""),
    ],
)
def test_recovery_rejects_expired_rows_without_complete_lease_ownership(
    snapshot_mutation,
) -> None:
    expired = replace(
        _queued_snapshot("a"),
        status=BuildJobStatus.CLAIMED,
        revision=2,
        worker=WorkerIdentity("worker-a", "in_process"),
        lease_token="correct-token",
        lease_expires_at=NOW,
    )
    connection = _FakeConnection([_Rows([_snapshot_row(snapshot_mutation(expired))])])
    repository = _make_repository(_FakePool([connection]))

    with pytest.raises(BuildJobRepositoryUnavailableError):
        repository.recover_expired_leases()

    assert len(connection.calls) == 1
    assert connection.transaction_outcomes == ["rollback"]


def test_retention_archives_excess_terminal_rows_then_purges_inclusive_cutoff() -> None:
    connection = _FakeConnection(
        [
            _Rows([]),
            _Rows([("a" * 32,), ("b" * 32,)]),
            _Rows([]),
            _Rows([]),
        ]
    )
    repository = _make_repository(
        _FakePool([connection]),
        settings=BuildJobRepositorySettings(retention_limit=1, audit_retention_days=90),
    )

    repository.apply_retention()

    assert connection.transaction_outcomes == ["commit"]
    archive_sql, archive_params = connection.calls[0]
    assert "ROW_NUMBER() OVER" in archive_sql
    assert "COALESCE(finished_at, created_at) DESC, job_id DESC" in archive_sql
    assert "ranked.retention_rank > %(retention_limit)s" in archive_sql
    assert archive_params == {"archived_at": NOW, "retention_limit": 1}
    purge_select_sql, purge_select_params = connection.calls[1]
    assert "archived_at <= %(cutoff)s" in purge_select_sql
    assert "FOR UPDATE SKIP LOCKED" in purge_select_sql
    assert purge_select_params == {"cutoff": NOW - timedelta(days=90), "limit": 100}
    assert "DELETE FROM graph_rag_control_plane.build_job_events" in connection.calls[2][0]
    assert "DELETE FROM graph_rag_control_plane.build_jobs" in connection.calls[3][0]
    assert connection.calls[2][1] == {"expired_job_ids": ["a" * 32, "b" * 32]}
    assert connection.calls[3][1] == {"expired_job_ids": ["a" * 32, "b" * 32]}


def test_repository_observers_classify_operations_errors_and_retention_without_identifiers() -> (
    None
):
    recorded_operations: list[tuple[str, str, str, float]] = []
    recorded_claims: list[tuple[str, str]] = []
    recorded_errors: list[tuple[str, str]] = []
    recorded_retention: list[tuple[str, str, int]] = []
    observers = PostgresBuildJobObservers(
        operation=lambda backend, operation, outcome, duration: recorded_operations.append(
            (backend, operation, outcome, duration)
        ),
        claim=lambda backend, outcome: recorded_claims.append((backend, outcome)),
        error=lambda backend, category: recorded_errors.append((backend, category)),
        retention=lambda backend, action, count: recorded_retention.append(
            (backend, action, count)
        ),
    )
    empty_claim = _FakeConnection([_Rows([])])
    repository = _make_repository(_FakePool([empty_claim]), settings=BuildJobRepositorySettings())
    repository._observers = observers

    assert repository.claim_next(WorkerIdentity("worker-a", "external_worker")) is None

    retention_connection = _FakeConnection(
        [_Rows([], rowcount=2), _Rows([("a" * 32,)]), _Rows([]), _Rows([])]
    )
    repository._pool = _FakePool([retention_connection])
    repository.apply_retention()

    unavailable_connection = _FakeConnection([_ConnectionFailure("dsn=postgresql://secret")])
    repository._pool = _FakePool([unavailable_connection])
    with pytest.raises(BuildJobRepositoryUnavailableError):
        repository.get(BuildJobId("a" * 32))

    assert [
        (backend, operation, outcome) for backend, operation, outcome, _ in recorded_operations
    ] == [
        ("postgresql", "claim", "empty"),
        ("postgresql", "apply_retention", "success"),
        ("postgresql", "get", "error"),
    ]
    assert recorded_claims == [("postgresql", "empty")]
    assert recorded_errors == [("postgresql", "connection")]
    assert recorded_retention == [("postgresql", "archived", 2), ("postgresql", "purged", 1)]


def test_observer_failure_does_not_change_repository_behavior() -> None:
    observers = PostgresBuildJobObservers(
        operation=lambda *_: (_ for _ in ()).throw(RuntimeError("metric failure")),
        claim=lambda *_: (_ for _ in ()).throw(RuntimeError("metric failure")),
        error=lambda *_: (_ for _ in ()).throw(RuntimeError("metric failure")),
        retention=lambda *_: (_ for _ in ()).throw(RuntimeError("metric failure")),
    )
    repository = _make_repository(_FakePool([_FakeConnection([_Rows([])])]))
    repository._observers = observers

    assert repository.claim_next(WorkerIdentity("worker-a", "external_worker")) is None


@pytest.mark.parametrize(
    ("category", "responses", "patch_claimed_event", "expected_exception"),
    [
        (
            "connection",
            [_ConnectionFailure("connection secret")],
            False,
            BuildJobRepositoryUnavailableError,
        ),
        (
            "data",
            [_Rows([("malformed",)])],
            False,
            BuildJobRepositoryUnavailableError,
        ),
        (
            "domain",
            [_Rows([_snapshot_row(_queued_snapshot())])],
            True,
            BuildJobRepositoryError,
        ),
    ],
)
def test_claim_failure_records_claim_error_and_one_repository_category(
    category: str,
    responses: list[_Rows | BaseException],
    patch_claimed_event: bool,
    expected_exception: type[Exception],
) -> None:
    operations: list[tuple[str, str, str, float]] = []
    claims: list[tuple[str, str]] = []
    errors: list[tuple[str, str]] = []
    observers = PostgresBuildJobObservers(
        operation=lambda backend, operation, outcome, duration: operations.append(
            (backend, operation, outcome, duration)
        ),
        claim=lambda backend, outcome: claims.append((backend, outcome)),
        error=lambda backend, error_category: errors.append((backend, error_category)),
        retention=lambda *_: None,
    )
    repository = _make_repository(_FakePool([_FakeConnection(responses)]))
    repository._observers = observers

    claim_patch = (
        patch.object(
            repository_module,
            "claimed_event",
            side_effect=BuildJobRepositoryError("domain failure"),
        )
        if patch_claimed_event
        else nullcontext()
    )
    with claim_patch, pytest.raises(expected_exception):
        repository.claim_next(WorkerIdentity("worker-a", "external_worker"))

    assert [(backend, operation, outcome) for backend, operation, outcome, _ in operations] == [
        ("postgresql", "claim", "error")
    ]
    assert claims == [("postgresql", "error")]
    assert errors == [("postgresql", category)]


@pytest.mark.parametrize(
    "responses",
    [
        [_Rows([], rowcount=2), _Rows([])],
        [_Rows([], rowcount=2), _Rows([("a" * 32,)]), _Rows([]), _ConnectionFailure("purge")],
    ],
)
def test_retention_metrics_are_not_emitted_for_rolled_back_transactions(
    responses: list[_Rows | BaseException],
) -> None:
    retained: list[tuple[str, str, int]] = []
    observers = PostgresBuildJobObservers(
        operation=lambda *_: None,
        claim=lambda *_: None,
        error=lambda *_: None,
        retention=lambda backend, action, count: retained.append((backend, action, count)),
    )
    repository = _make_repository(_FakePool([_CommitFailureConnection(responses)]))
    repository._observers = observers

    with pytest.raises(BuildJobRepositoryUnavailableError):
        repository.apply_retention()

    assert retained == []


def test_constructor_schema_failure_observes_only_fixed_categories() -> None:
    pool = _FakePool()
    operations: list[tuple[str, str, str, float]] = []
    errors: list[tuple[str, str]] = []
    observers = PostgresBuildJobObservers(
        operation=lambda backend, operation, outcome, duration: operations.append(
            (backend, operation, outcome, duration)
        ),
        claim=lambda *_: None,
        error=lambda backend, category: errors.append((backend, category)),
        retention=lambda *_: None,
    )
    schema_manager = SimpleNamespace(
        verify=unittest.mock.Mock(
            side_effect=BuildJobRepositoryError("schema dsn=postgresql://secret SQL=private")
        )
    )

    with (
        patch.object(repository_module, "ConnectionPool", return_value=pool),
        patch.object(
            repository_module,
            "PostgresBuildJobSchemaManager",
            return_value=schema_manager,
        ),
        pytest.raises(BuildJobRepositoryError),
    ):
        PostgresBuildJobRepository(
            "postgresql://user:dsn-secret@unit-test.invalid/jobs",
            now=lambda: NOW,
            settings=BuildJobRepositorySettings(),
            observers=observers,
        )

    assert [(backend, operation, outcome) for backend, operation, outcome, _ in operations] == [
        ("postgresql", "initialize", "error")
    ]
    assert errors == [("postgresql", "domain")]


def test_diagnostics_is_bounded_and_returns_safe_fixed_warning_on_failure() -> None:
    connection = _FakeConnection([_ConnectionFailure("dsn=postgresql://secret raw SQL params")])
    repository = _make_repository(_FakePool([connection]))

    diagnostics = repository.diagnostics()

    assert diagnostics.backend == "postgresql"
    assert diagnostics.ready is False
    assert diagnostics.schema_version == "3"
    assert [warning.code for warning in diagnostics.warnings] == ["BUILD_JOB_POSTGRES_UNAVAILABLE"]
    assert all("secret" not in repr(warning) for warning in diagnostics.warnings)
    assert len(connection.calls) == 1
    assert connection.calls[0] == ("SELECT 1", None)


def test_diagnostics_verifies_connectivity_and_schema_without_scanning_jobs() -> None:
    connection = _FakeConnection([_Rows([(1,)])])
    repository = _make_repository(_FakePool([connection]))
    schema_manager = SimpleNamespace(verify=unittest.mock.Mock())
    repository._schema_manager = schema_manager

    diagnostics = repository.diagnostics()

    assert diagnostics == BuildJobRepositoryDiagnostics(
        backend="postgresql",
        ready=True,
        schema_version="3",
    )
    assert connection.calls == [("SELECT 1", None)]
    schema_manager.verify.assert_called_once_with()


def test_diagnostics_schema_failure_never_returns_raw_exception_details() -> None:
    connection = _FakeConnection([_Rows([(1,)])])
    repository = _make_repository(_FakePool([connection]))
    repository._schema_manager = SimpleNamespace(
        verify=unittest.mock.Mock(
            side_effect=RuntimeError(
                "dsn=postgresql://user:secret@host/jobs SQL=SELECT params=('private',)"
            )
        )
    )

    diagnostics = repository.diagnostics()

    assert diagnostics.ready is False
    assert diagnostics.warnings[0].code == "BUILD_JOB_POSTGRES_UNAVAILABLE"
    rendered = repr(diagnostics)
    assert "secret" not in rendered
    assert "SELECT" not in rendered
    assert "private" not in rendered
    assert connection.calls == [("SELECT 1", None)]


@pytest.fixture
def migrated_postgres_dsn(postgres_dsn: str) -> str:
    PostgresBuildJobSchemaManager(postgres_dsn).migrate()
    return postgres_dsn


@pytest.fixture
def repository_factory(
    migrated_postgres_dsn: str,
) -> Iterator[Callable[..., PostgresBuildJobRepository]]:
    repositories: list[PostgresBuildJobRepository] = []

    def factory(
        *,
        clock: MutableClock | None = None,
        settings: BuildJobRepositorySettings | None = None,
    ) -> PostgresBuildJobRepository:
        resolved_clock = clock or MutableClock(NOW)
        repository = PostgresBuildJobRepository(
            migrated_postgres_dsn,
            now=resolved_clock.now,
            settings=settings or BuildJobRepositorySettings(),
            pool_min_size=1,
            pool_max_size=4,
            pool_timeout_seconds=5.0,
        )
        repositories.append(repository)
        return repository

    yield factory
    for repository in repositories:
        repository.close()


@pytest.fixture
def postgres_contract_repository(
    request: pytest.FixtureRequest,
    migrated_postgres_dsn: str,
) -> Iterator[None]:
    instance = request.instance
    assert instance is not None
    instance._postgres_dsn = migrated_postgres_dsn
    instance._postgres_repositories = []
    yield
    for repository in instance._postgres_repositories:
        repository.close()


@pytest.mark.usefixtures("postgres_contract_repository")
class PostgresBuildJobRepositoryContractTests(
    BuildJobRepositoryContractTests,
    unittest.TestCase,
):
    _postgres_dsn: str
    _postgres_repositories: list[PostgresBuildJobRepository]

    def make_repository(
        self,
        clock: MutableClock,
        settings: BuildJobRepositorySettings,
    ) -> PostgresBuildJobRepository:
        repository = PostgresBuildJobRepository(
            self._postgres_dsn,
            now=clock.now,
            settings=settings,
            pool_min_size=1,
            pool_max_size=4,
            pool_timeout_seconds=5.0,
        )
        self._postgres_repositories.append(repository)
        return repository


def test_same_idempotency_key_race_returns_one_job(repository_factory) -> None:
    repository = repository_factory()
    commands = [
        SubmitBuildJob(
            job_id=BuildJobId(character * 32),
            request_id=f"request-{character}",
            job_type=BuildJobType.BUILD,
            idempotency_key="stable-race-key",
        )
        for character in ("a", "b")
    ]

    with ThreadPoolExecutor(max_workers=2) as executor:
        submissions = list(executor.map(repository.submit, commands))

    assert len({item.snapshot.job_id for item in submissions}) == 1
    assert {item.disposition for item in submissions} == {
        BuildJobSubmissionDisposition.CREATED,
        BuildJobSubmissionDisposition.REPLAYED,
    }


def test_same_idempotency_key_with_different_job_type_conflicts(
    repository_factory,
) -> None:
    repository = repository_factory()
    repository.submit(
        SubmitBuildJob(
            job_id=BuildJobId("a" * 32),
            request_id="request-a",
            job_type=BuildJobType.BUILD,
            idempotency_key="stable-key",
        )
    )

    with pytest.raises(BuildJobIdempotencyConflictError):
        repository.submit(
            SubmitBuildJob(
                job_id=BuildJobId("b" * 32),
                request_id="request-b",
                job_type=BuildJobType.REBUILD,
                idempotency_key="stable-key",
            )
        )


def test_different_keys_racing_for_active_slot_return_one_conflict(
    repository_factory,
) -> None:
    repository = repository_factory()
    commands = [
        SubmitBuildJob(
            job_id=BuildJobId(character * 32),
            request_id=f"request-{character}",
            job_type=BuildJobType.BUILD,
            idempotency_key=f"key-{character}",
        )
        for character in ("a", "b")
    ]

    def submit(command: SubmitBuildJob):
        try:
            return repository.submit(command)
        except BuildJobConflictError as error:
            return error

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(submit, commands))

    assert len([item for item in outcomes if not isinstance(item, BuildJobConflictError)]) == 1
    conflicts = [item for item in outcomes if isinstance(item, BuildJobConflictError)]
    assert len(conflicts) == 1
    assert conflicts[0].snapshot.status is BuildJobStatus.QUEUED


def _insert_snapshot(
    dsn: str,
    snapshot: BuildJobSnapshot,
    *,
    archived_at: datetime | None = None,
    events: tuple[BuildJobEvent, ...] = (),
) -> None:
    worker = snapshot.worker
    with psycopg.connect(dsn) as connection:
        connection.execute(
            """
            INSERT INTO graph_rag_control_plane.build_jobs (
                job_id, request_id, job_type, status, revision,
                created_at, started_at, finished_at, message, error, logs, result,
                retry_of_job_id, idempotency_key_hash, worker_id, runner_backend,
                lease_token, lease_expires_at, archived_at, updated_at
            ) VALUES (
                %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s,
                %s, %s, %s, %s
            )
            """,
            (
                str(snapshot.job_id),
                snapshot.request_id,
                snapshot.job_type.value,
                snapshot.status.value,
                snapshot.revision,
                snapshot.created_at,
                snapshot.started_at,
                snapshot.finished_at,
                snapshot.message,
                Jsonb(dict(snapshot.error)) if snapshot.error is not None else None,
                Jsonb(list(snapshot.logs)),
                Jsonb(dict(snapshot.result)) if snapshot.result is not None else None,
                str(snapshot.retry_of_job_id) if snapshot.retry_of_job_id else None,
                snapshot.idempotency_key_hash,
                worker.worker_id if worker is not None else None,
                worker.runner_backend if worker is not None else None,
                snapshot.lease_token,
                snapshot.lease_expires_at,
                archived_at,
                NOW,
            ),
        )
        for event in events:
            payload = event_to_dict(event)
            connection.execute(
                """
                INSERT INTO graph_rag_control_plane.build_job_events (
                    event_id, job_id, revision, event_type,
                    schema_version, occurred_at, request_id, payload
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    event.event_id,
                    str(event.job_id),
                    event.revision,
                    event.event_type.value,
                    event.schema_version,
                    event.occurred_at,
                    event.request_id,
                    Jsonb(payload["payload"]),
                ),
            )


def test_get_and_list_preserve_exact_row_values_and_keyset_order(
    migrated_postgres_dsn: str,
    repository_factory,
) -> None:
    older = _snapshot("d", created_at=NOW)
    newer = _snapshot("e", created_at=NOW + timedelta(seconds=1))
    _insert_snapshot(
        migrated_postgres_dsn,
        older,
        events=(_queued_event(older),),
    )
    _insert_snapshot(
        migrated_postgres_dsn,
        newer,
        events=(_queued_event(newer),),
    )
    repository = repository_factory(
        settings=BuildJobRepositorySettings(list_default_limit=1, list_max_limit=1)
    )

    assert repository.get(older.job_id) == older
    first_page = repository.list_page(BuildJobListQuery(limit=50))
    second_page = repository.list_page(BuildJobListQuery(limit=50, cursor=first_page.next_cursor))

    assert first_page.jobs == (newer,)
    assert first_page.next_cursor
    assert second_page.jobs == (older,)
    assert second_page.next_cursor == ""


def test_archived_rows_are_hidden_from_current_reads_but_events_remain_pageable(
    migrated_postgres_dsn: str,
    repository_factory,
) -> None:
    archived = _snapshot("e")
    queued = _queued_event(archived)
    started = BuildJobEvent(
        event_id=f"{archived.job_id}:2",
        job_id=archived.job_id,
        revision=2,
        event_type=BuildJobEventType.STARTED,
        schema_version=1,
        occurred_at=NOW + timedelta(seconds=1),
        request_id=archived.request_id,
        payload=JobStarted(archived.worker or WorkerIdentity("worker-e", "external_worker")),
    )
    _insert_snapshot(
        migrated_postgres_dsn,
        archived,
        archived_at=NOW,
        events=(queued, started),
    )
    repository = repository_factory(
        settings=BuildJobRepositorySettings(list_default_limit=1, list_max_limit=1)
    )

    assert repository.get(archived.job_id) is None
    assert repository.list_page(BuildJobListQuery()).jobs == ()
    first_page = repository.list_events(
        archived.job_id,
        BuildJobEventListQuery(limit=1),
    )
    second_page = repository.list_events(
        archived.job_id,
        BuildJobEventListQuery(limit=1, cursor=first_page.next_cursor),
    )

    assert [event.revision for event in first_page.events] == [1]
    assert first_page.next_cursor
    assert [event.revision for event in second_page.events] == [2]
    assert second_page.next_cursor == ""


def test_event_listing_linearizes_with_physical_purge(
    migrated_postgres_dsn: str,
    repository_factory,
) -> None:
    clock = MutableClock(NOW)
    settings = BuildJobRepositorySettings(
        retention_limit=0,
        audit_retention_days=90,
        list_max_limit=100,
    )
    reader = repository_factory(clock=clock, settings=settings)
    purger = repository_factory(clock=clock, settings=settings)
    archived = submit_and_succeed(
        reader,
        "9" * 32,
        clock=clock,
        key="linearized-purge-key",
    )
    clock.advance(seconds=90 * 86400)
    before_event_query = threading.Event()
    allow_event_query = threading.Event()
    original_pool = reader._pool

    class BarrierConnection:
        def __init__(self, connection) -> None:
            self._connection = connection

        def transaction(self):
            return self._connection.transaction()

        def execute(self, query, params=None):
            if str(query) == repository_module._EVENT_LIST_SQL:
                before_event_query.set()
                assert allow_event_query.wait(timeout=10.0)
            return self._connection.execute(query, params)

    class BarrierCheckout(AbstractContextManager[BarrierConnection]):
        def __init__(self, timeout: float | None) -> None:
            self._checkout = original_pool.connection(timeout=timeout)
            self._connection = None

        def __enter__(self) -> BarrierConnection:
            self._connection = self._checkout.__enter__()
            return BarrierConnection(self._connection)

        def __exit__(self, exc_type, exc, traceback) -> bool:
            return self._checkout.__exit__(exc_type, exc, traceback)

    class BarrierPool:
        def connection(self, timeout: float | None = None) -> BarrierCheckout:
            return BarrierCheckout(timeout)

        def close(self) -> None:
            original_pool.close()

    reader._pool = BarrierPool()

    with ThreadPoolExecutor(max_workers=2) as executor:
        event_future = executor.submit(
            reader.list_events,
            archived.job_id,
            BuildJobEventListQuery(limit=100),
        )
        assert before_event_query.wait(timeout=5.0)
        purge_future = executor.submit(purger.apply_retention)
        try:
            purge_future.result(timeout=5.0)
            with psycopg.connect(migrated_postgres_dsn) as connection:
                persisted = connection.execute(
                    """
                    SELECT
                        EXISTS (
                            SELECT 1
                            FROM graph_rag_control_plane.build_jobs
                            WHERE job_id = %s
                        ),
                        (
                            SELECT count(*)
                            FROM graph_rag_control_plane.build_job_events
                            WHERE job_id = %s
                        )
                    """,
                    (str(archived.job_id), str(archived.job_id)),
                ).fetchone()
            assert persisted == (True, 4)
        finally:
            allow_event_query.set()
        page = event_future.result(timeout=10.0)

    assert tuple(event.revision for event in page.events) == (1, 2, 3, 4)
    purger.apply_retention()
    with pytest.raises(BuildJobNotFoundError):
        reader.list_events(archived.job_id, BuildJobEventListQuery(limit=100))


def _race_two(callable_one, callable_two) -> tuple[object, object]:
    barrier = threading.Barrier(2)

    def synchronized(callable_item):
        barrier.wait(timeout=5.0)
        try:
            return callable_item()
        except Exception as error:
            return error

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(synchronized, callable_one)
        second = executor.submit(synchronized, callable_two)
        return first.result(timeout=10.0), second.result(timeout=10.0)


def _revisions(
    repository: PostgresBuildJobRepository,
    job_id: BuildJobId,
) -> tuple[int, ...]:
    page = repository.list_events(job_id, BuildJobEventListQuery(limit=100))
    assert page.next_cursor == ""
    return tuple(event.revision for event in page.events)


def test_claim_race_returns_one_effective_lease(
    repository_factory,
) -> None:
    repository = repository_factory()
    submitted = repository.submit(
        SubmitBuildJob(
            job_id=BuildJobId("a" * 32),
            request_id="request-a",
            job_type=BuildJobType.BUILD,
        )
    ).snapshot
    first_worker = WorkerIdentity("worker-1", "in_process")
    second_worker = WorkerIdentity("worker-2", "external_worker")

    outcomes = _race_two(
        lambda: repository.claim_next(first_worker),
        lambda: repository.claim_next(second_worker),
    )

    leases = [outcome for outcome in outcomes if isinstance(outcome, BuildJobLease)]
    assert len(leases) == 1
    assert sum(outcome is None for outcome in outcomes) == 1
    assert leases[0].job_id == submitted.job_id
    assert _revisions(repository, submitted.job_id) == (1, 2)


def test_lease_owner_token_revision_and_expiry_boundary_are_enforced(
    repository_factory,
) -> None:
    clock = MutableClock(NOW)
    repository = repository_factory(
        clock=clock,
        settings=BuildJobRepositorySettings(lease_seconds=30),
    )
    submitted = repository.submit(
        SubmitBuildJob(
            job_id=BuildJobId("a" * 32),
            request_id="request-a",
            job_type=BuildJobType.BUILD,
        )
    ).snapshot
    worker = WorkerIdentity("worker-1", "in_process")
    lease = repository.claim_next(worker)
    assert lease is not None

    invalid_leases = (
        replace(lease, revision=lease.revision - 1),
        replace(lease, worker=WorkerIdentity("worker-2", "in_process")),
        replace(lease, lease_token="wrong-token"),
    )
    for invalid in invalid_leases:
        with pytest.raises(BuildJobLeaseLostError):
            repository.renew_lease(invalid)

    clock.advance(seconds=30)
    with pytest.raises(BuildJobLeaseLostError):
        repository.renew_lease(lease)
    claimed = repository.get(submitted.job_id)
    assert claimed is not None
    assert claimed.revision == 2
    assert _revisions(repository, submitted.job_id) == (1, 2)


def test_competing_applies_at_one_revision_have_one_winner(
    repository_factory,
) -> None:
    repository = repository_factory()
    submitted = repository.submit(
        SubmitBuildJob(
            job_id=BuildJobId("a" * 32),
            request_id="request-a",
            job_type=BuildJobType.BUILD,
        )
    ).snapshot
    worker = WorkerIdentity("worker-1", "in_process")
    lease = repository.claim_next(worker)
    claimed = repository.get(submitted.job_id)
    assert lease is not None
    assert claimed is not None
    event = _started_event(claimed, worker)

    outcomes = _race_two(
        lambda: repository.apply(
            event,
            expected_revision=claimed.revision,
            lease=lease,
        ),
        lambda: repository.apply(
            event,
            expected_revision=claimed.revision,
            lease=lease,
        ),
    )

    assert len([outcome for outcome in outcomes if isinstance(outcome, BuildJobSnapshot)]) == 1
    errors = [outcome for outcome in outcomes if isinstance(outcome, BuildJobConcurrentUpdateError)]
    assert len(errors) == 1
    assert _revisions(repository, submitted.job_id) == (1, 2, 3)


def test_projection_failure_rolls_back_the_inserted_event(
    migrated_postgres_dsn: str,
    repository_factory,
) -> None:
    repository = repository_factory()
    submitted = repository.submit(
        SubmitBuildJob(
            job_id=BuildJobId("a" * 32),
            request_id="request-a",
            job_type=BuildJobType.BUILD,
        )
    ).snapshot
    worker = WorkerIdentity("worker-1", "in_process")
    lease = repository.claim_next(worker)
    claimed = repository.get(submitted.job_id)
    assert lease is not None
    assert claimed is not None
    with psycopg.connect(migrated_postgres_dsn, autocommit=True) as connection:
        connection.execute(
            """
            CREATE FUNCTION graph_rag_control_plane.reject_projection_update()
            RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN
                RAISE EXCEPTION 'forced projection update failure';
            END;
            $$
            """
        )
        connection.execute(
            """
            CREATE TRIGGER reject_projection_update
            BEFORE UPDATE ON graph_rag_control_plane.build_jobs
            FOR EACH ROW
            EXECUTE FUNCTION graph_rag_control_plane.reject_projection_update()
            """
        )
    try:
        with pytest.raises(BuildJobRepositoryUnavailableError):
            repository.apply(
                _started_event(claimed, worker),
                expected_revision=claimed.revision,
                lease=lease,
            )
        restored = repository.get(submitted.job_id)
        assert restored is not None
        assert restored.revision == claimed.revision
        assert _revisions(repository, submitted.job_id) == (1, 2)
    finally:
        with psycopg.connect(migrated_postgres_dsn, autocommit=True) as connection:
            connection.execute(
                """
                DROP TRIGGER IF EXISTS reject_projection_update
                ON graph_rag_control_plane.build_jobs
                """
            )
            connection.execute(
                """
                DROP FUNCTION IF EXISTS
                graph_rag_control_plane.reject_projection_update()
                """
            )


def test_recovery_race_interrupts_an_expired_lease_once(
    repository_factory,
) -> None:
    clock = MutableClock(NOW)
    repository = repository_factory(
        clock=clock,
        settings=BuildJobRepositorySettings(lease_seconds=30),
    )
    submitted = repository.submit(
        SubmitBuildJob(
            job_id=BuildJobId("a" * 32),
            request_id="request-a",
            job_type=BuildJobType.BUILD,
        )
    ).snapshot
    lease = repository.claim_next(WorkerIdentity("worker-1", "in_process"))
    assert lease is not None
    clock.advance(seconds=30)

    outcomes = _race_two(
        repository.recover_expired_leases,
        repository.recover_expired_leases,
    )

    assert all(isinstance(outcome, tuple) for outcome in outcomes)
    recovered = [snapshot for outcome in outcomes for snapshot in outcome]
    assert [snapshot.job_id for snapshot in recovered] == [submitted.job_id]
    restored = repository.get(submitted.job_id)
    assert restored is not None
    assert restored.status is BuildJobStatus.INTERRUPTED
    assert _revisions(repository, submitted.job_id) == (1, 2, 3)


def test_retention_archives_only_excess_terminal_jobs_and_purges_at_cutoff(
    repository_factory,
) -> None:
    clock = MutableClock(NOW)
    repository = repository_factory(
        clock=clock,
        settings=BuildJobRepositorySettings(
            retention_limit=1,
            audit_retention_days=90,
            list_max_limit=100,
        ),
    )
    oldest = submit_and_succeed(
        repository,
        "a" * 32,
        clock=clock,
        key="purge-key",
    )
    clock.advance(seconds=1)
    newest = submit_and_succeed(
        repository,
        "b" * 32,
        clock=clock,
        key="keep-key",
    )

    assert repository.get(oldest.job_id) is None
    assert repository.get(newest.job_id) == newest
    assert _revisions(repository, oldest.job_id) == (1, 2, 3, 4)
    clock.advance(seconds=90 * 86400)

    repository.apply_retention()

    with pytest.raises(BuildJobNotFoundError):
        repository.list_events(oldest.job_id, BuildJobEventListQuery())
    assert repository.get(newest.job_id) == newest
    recreated = repository.submit(
        SubmitBuildJob(
            job_id=BuildJobId("c" * 32),
            request_id="request-c",
            job_type=BuildJobType.BUILD,
            idempotency_key="purge-key",
        )
    )
    assert recreated.disposition is BuildJobSubmissionDisposition.CREATED

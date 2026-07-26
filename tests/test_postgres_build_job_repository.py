from __future__ import annotations

import logging
import unittest
from collections.abc import Callable, Iterator, Mapping
from concurrent.futures import ThreadPoolExecutor
from contextlib import AbstractContextManager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

import psycopg
import pytest
from psycopg.types.json import Jsonb

from rag_modules.app.build_jobs import (
    BuildJobConflictError,
    BuildJobEvent,
    BuildJobEventListQuery,
    BuildJobEventType,
    BuildJobId,
    BuildJobIdempotencyConflictError,
    BuildJobListQuery,
    BuildJobNotFoundError,
    BuildJobRepositoryError,
    BuildJobRepositorySettings,
    BuildJobRepositoryUnavailableError,
    BuildJobSnapshot,
    BuildJobStatus,
    BuildJobSubmissionDisposition,
    BuildJobType,
    JobQueued,
    JobStarted,
    SubmitBuildJob,
    WorkerIdentity,
    event_to_dict,
)
from rag_modules.runtime.build_jobs.postgres import (
    PostgresBuildJobRepository,
    PostgresBuildJobSchemaManager,
)
from rag_modules.runtime.build_jobs.postgres import repository as repository_module
from tests.build_job_repository_contract import (
    BuildJobRepositorySubmissionContractTests,
    MutableClock,
)

pytest_plugins = ("tests.postgres_build_job_helpers",)

NOW = datetime(2026, 7, 26, tzinfo=timezone.utc)
_Now = Callable[[], datetime]


class _Rows:
    def __init__(self, rows: list[tuple[object, ...]]) -> None:
        self._rows = rows

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

    def open(self, *, wait: bool, timeout: float) -> None:
        self.open_calls.append((wait, timeout))

    def connection(self, timeout: float | None = None) -> _PoolConnection:
        self.checkout_timeouts.append(timeout)
        if not self._connections:
            raise AssertionError("Unexpected pool checkout.")
        return _PoolConnection(self._connections.pop(0))

    def close(self) -> None:
        self.close_calls += 1


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

    assert pool_class.call_args.kwargs == {
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
    connection = _FakeConnection([_Rows([]), _Rows([]), _Rows([])])
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
    assert len(connection.calls) == 3
    assert all("OFFSET" not in statement.upper() for statement, _params in connection.calls)
    projection_parameters = connection.calls[1][1]
    event_parameters = connection.calls[2][1]
    assert isinstance(projection_parameters, tuple)
    assert isinstance(event_parameters, tuple)
    assert projection_parameters[9] is None
    assert isinstance(projection_parameters[10], Jsonb)
    assert projection_parameters[11] is None
    assert isinstance(event_parameters[-1], Jsonb)
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
    event_sql, event_params = first_connection.calls[1]
    assert "revision > %(cursor_revision)s" in event_sql
    assert "ORDER BY revision" in event_sql
    assert "OFFSET" not in event_sql.upper()
    assert event_params == {
        "job_id": str(snapshot.job_id),
        "cursor_revision": 0,
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


def test_missing_event_subject_raises_not_found() -> None:
    job_id = BuildJobId("f" * 32)
    connection = _FakeConnection([_Rows([(False, False)])])
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
class PostgresBuildJobRepositorySubmissionContractTests(
    BuildJobRepositorySubmissionContractTests,
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

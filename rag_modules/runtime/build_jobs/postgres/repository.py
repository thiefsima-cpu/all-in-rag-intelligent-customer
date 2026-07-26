"""PostgreSQL submission and read operations for the build-job control plane."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
from typing import Never

import psycopg
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

from rag_modules.contracts.build_jobs import (
    BuildJobConflictError,
    BuildJobEvent,
    BuildJobEventListQuery,
    BuildJobEventPage,
    BuildJobId,
    BuildJobIdempotencyConflictError,
    BuildJobLease,
    BuildJobListQuery,
    BuildJobNotFoundError,
    BuildJobPage,
    BuildJobRepositoryDiagnostics,
    BuildJobRepositoryError,
    BuildJobRepositorySettings,
    BuildJobRepositoryUnavailableError,
    BuildJobSnapshot,
    BuildJobStatus,
    BuildJobSubmission,
    BuildJobSubmissionDisposition,
    BuildJobType,
    SubmitBuildJob,
    WorkerIdentity,
    event_from_dict,
    event_to_dict,
    reduce_build_job,
)
from rag_modules.kernel.json_types import JsonObject, coerce_json_object
from rag_modules.runtime.build_jobs.file_repository_codecs import (
    decode_cursor,
    decode_event_cursor,
    encode_cursor,
    encode_event_cursor,
)
from rag_modules.runtime.build_jobs.file_repository_events import (
    hash_idempotency_key,
    new_queued_event,
    validate_idempotency_key,
)

from .schema import PostgresBuildJobSchemaManager

_LOGGER = logging.getLogger(__name__)
_BACKEND = "postgresql"
_DATABASE_FAILURE_MESSAGE = "Build job PostgreSQL repository operation failed."
_UNAVAILABLE_MESSAGE = "Build job repository is unavailable."

_SNAPSHOT_COLUMNS = """
    job_id, request_id, job_type, status, revision,
    created_at, started_at, finished_at, message, error, logs, result,
    retry_of_job_id, idempotency_key_hash, worker_id, runner_backend,
    lease_token, lease_expires_at, archived_at
"""
_SELECT_IDEMPOTENCY_SQL = f"""
SELECT {_SNAPSHOT_COLUMNS}
FROM graph_rag_control_plane.build_jobs
WHERE idempotency_key_hash = %(idempotency_key_hash)s
"""
_SELECT_ACTIVE_SQL = f"""
SELECT {_SNAPSHOT_COLUMNS}
FROM graph_rag_control_plane.build_jobs
WHERE archived_at IS NULL
  AND status IN ('queued', 'claimed', 'running', 'cancel_requested')
"""
_GET_SQL = f"""
SELECT {_SNAPSHOT_COLUMNS}
FROM graph_rag_control_plane.build_jobs
WHERE job_id = %(job_id)s AND archived_at IS NULL
"""
_LIST_SQL = f"""
SELECT {_SNAPSHOT_COLUMNS}
FROM graph_rag_control_plane.build_jobs
WHERE archived_at IS NULL
  AND (
      %(cursor_created_at)s IS NULL
      OR (created_at, job_id) < (%(cursor_created_at)s, %(cursor_job_id)s)
  )
ORDER BY created_at DESC, job_id DESC
LIMIT %(fetch_limit)s
"""
_LIST_STATUS_SQL = f"""
SELECT {_SNAPSHOT_COLUMNS}
FROM graph_rag_control_plane.build_jobs
WHERE archived_at IS NULL
  AND status = %(status)s
  AND (
      %(cursor_created_at)s IS NULL
      OR (created_at, job_id) < (%(cursor_created_at)s, %(cursor_job_id)s)
  )
ORDER BY created_at DESC, job_id DESC
LIMIT %(fetch_limit)s
"""
_EVENT_SUBJECT_SQL = """
SELECT
    EXISTS (
        SELECT 1
        FROM graph_rag_control_plane.build_jobs
        WHERE job_id = %(job_id)s
    ),
    EXISTS (
        SELECT 1
        FROM graph_rag_control_plane.build_job_events
        WHERE job_id = %(job_id)s
    )
"""
_EVENT_LIST_SQL = """
SELECT event_id, job_id, revision, event_type, schema_version, occurred_at, request_id, payload
FROM graph_rag_control_plane.build_job_events
WHERE job_id = %(job_id)s AND revision > %(cursor_revision)s
ORDER BY revision
LIMIT %(fetch_limit)s
"""
_INSERT_SNAPSHOT_SQL = """
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
"""
_INSERT_EVENT_SQL = """
INSERT INTO graph_rag_control_plane.build_job_events (
    event_id, job_id, revision, event_type,
    schema_version, occurred_at, request_id, payload
) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
"""

_IDEMPOTENCY_CONSTRAINT = "build_jobs_idempotency_uq"
_ACTIVE_CONSTRAINT = "build_jobs_one_active_uq"
_Now = Callable[[], datetime]


class _PersistedDataError(RuntimeError):
    pass


class PostgresBuildJobRepository:
    """Own a Psycopg pool and persist current projections with append-only audit events."""

    def __init__(
        self,
        dsn: str,
        *,
        now: _Now,
        settings: BuildJobRepositorySettings | None = None,
        pool_min_size: int = 1,
        pool_max_size: int = 10,
        pool_timeout_seconds: float = 5.0,
    ) -> None:
        self._now = now
        self.settings = settings or BuildJobRepositorySettings()
        self._pool_timeout_seconds = float(pool_timeout_seconds)
        self._pool = ConnectionPool(
            conninfo=dsn,
            min_size=int(pool_min_size),
            max_size=int(pool_max_size),
            open=False,
            timeout=self._pool_timeout_seconds,
        )
        self._close_lock = threading.Lock()
        self._closed = False
        try:
            self._pool.open(wait=True, timeout=self._pool_timeout_seconds)
        except psycopg.Error as error:
            self._close_after_failed_start()
            self._raise_unavailable("open", error)
        try:
            PostgresBuildJobSchemaManager(dsn).verify()
        except BuildJobRepositoryError:
            self._close_after_failed_start()
            raise
        except Exception as error:
            self._close_after_failed_start()
            self._raise_unavailable("verify_schema", error)

    @property
    def list_default_limit(self) -> int:
        return self.settings.list_default_limit

    def submit(self, command: SubmitBuildJob) -> BuildJobSubmission:
        key_hash = hash_idempotency_key(validate_idempotency_key(command.idempotency_key))
        try:
            with self._pool.connection(timeout=self._pool_timeout_seconds) as connection:
                with connection.transaction():
                    existing = self._lookup_idempotency(connection, key_hash)
                    if existing is not None:
                        return self._idempotent_submission(existing, command)
                    event = new_queued_event(command, key_hash=key_hash, now=self._now())
                    snapshot = reduce_build_job(None, event)
                    connection.execute(
                        _INSERT_SNAPSHOT_SQL,
                        self._snapshot_values(
                            snapshot,
                            archived_at=None,
                            updated_at=event.occurred_at,
                        ),
                    )
                    connection.execute(_INSERT_EVENT_SQL, self._event_values(event))
            return BuildJobSubmission(BuildJobSubmissionDisposition.CREATED, snapshot)
        except psycopg.errors.UniqueViolation as error:
            return self._resolve_submit_unique_violation(error, command, key_hash)
        except psycopg.Error as error:
            self._raise_unavailable("submit", error)
        except _PersistedDataError as error:
            self._raise_unavailable("submit", error)

    def get(self, job_id: BuildJobId) -> BuildJobSnapshot | None:
        try:
            with self._pool.connection(timeout=self._pool_timeout_seconds) as connection:
                with connection.transaction():
                    row = connection.execute(
                        _GET_SQL,
                        {"job_id": str(job_id)},
                    ).fetchone()
                    return self._snapshot_from_row(row) if row is not None else None
        except psycopg.Error as error:
            self._raise_unavailable("get", error)
        except _PersistedDataError as error:
            self._raise_unavailable("get", error)

    def list_page(self, query: BuildJobListQuery) -> BuildJobPage:
        decoded_cursor = decode_cursor(query.cursor)
        cursor_created_at, cursor_job_id = decoded_cursor or (None, None)
        bounded_limit = self._bounded_limit(query.limit)
        parameters: dict[str, object] = {
            "cursor_created_at": cursor_created_at,
            "cursor_job_id": cursor_job_id,
            "fetch_limit": bounded_limit + 1,
        }
        statement = _LIST_SQL
        if query.status is not None:
            statement = _LIST_STATUS_SQL
            parameters["status"] = query.status.value
        try:
            with self._pool.connection(timeout=self._pool_timeout_seconds) as connection:
                with connection.transaction():
                    rows = connection.execute(statement, parameters).fetchall()
                    snapshots = tuple(self._snapshot_from_row(row) for row in rows)
        except psycopg.Error as error:
            self._raise_unavailable("list", error)
        except _PersistedDataError as error:
            self._raise_unavailable("list", error)

        selected = snapshots[:bounded_limit]
        next_cursor = ""
        if len(snapshots) > bounded_limit:
            last = selected[-1]
            next_cursor = encode_cursor(last.created_at.isoformat(), str(last.job_id))
        return BuildJobPage(jobs=selected, next_cursor=next_cursor)

    def list_events(
        self,
        job_id: BuildJobId,
        query: BuildJobEventListQuery,
    ) -> BuildJobEventPage:
        cursor_revision = decode_event_cursor(query.cursor)
        bounded_limit = self._bounded_limit(query.limit)
        subject_parameters = {"job_id": str(job_id)}
        event_parameters = {
            "job_id": str(job_id),
            "cursor_revision": cursor_revision,
            "fetch_limit": bounded_limit + 1,
        }
        try:
            with self._pool.connection(timeout=self._pool_timeout_seconds) as connection:
                with connection.transaction():
                    subject = connection.execute(
                        _EVENT_SUBJECT_SQL,
                        subject_parameters,
                    ).fetchone()
                    job_exists, events_exist = self._event_subject_state(subject)
                    if not job_exists:
                        raise BuildJobNotFoundError(job_id)
                    if not events_exist:
                        raise _PersistedDataError
                    rows = connection.execute(_EVENT_LIST_SQL, event_parameters).fetchall()
                    events = tuple(self._event_from_row(row) for row in rows)
        except psycopg.Error as error:
            self._raise_unavailable("list_events", error)
        except _PersistedDataError as error:
            self._raise_unavailable("list_events", error)

        selected = events[:bounded_limit]
        next_cursor = ""
        if len(events) > bounded_limit:
            next_cursor = encode_event_cursor(selected[-1].revision)
        return BuildJobEventPage(events=selected, next_cursor=next_cursor)

    def claim_next(self, worker: WorkerIdentity) -> BuildJobLease | None:
        del worker
        raise NotImplementedError("PostgreSQL build job claiming is implemented in Task 6.")

    def renew_lease(self, lease: BuildJobLease) -> BuildJobLease:
        del lease
        raise NotImplementedError("PostgreSQL build job lease renewal is implemented in Task 6.")

    def apply(
        self,
        event: BuildJobEvent,
        *,
        expected_revision: int,
        lease: BuildJobLease | None = None,
    ) -> BuildJobSnapshot:
        del event, expected_revision, lease
        raise NotImplementedError(
            "PostgreSQL build job event application is implemented in Task 6."
        )

    def find_dispatchable(self, *, limit: int) -> tuple[BuildJobId, ...]:
        del limit
        raise NotImplementedError("PostgreSQL dispatch lookup is implemented in Task 6.")

    def recover_expired_leases(self) -> tuple[BuildJobSnapshot, ...]:
        raise NotImplementedError("PostgreSQL lease recovery is implemented in Task 6.")

    def apply_retention(self) -> None:
        raise NotImplementedError("PostgreSQL retention is implemented in Task 6.")

    def diagnostics(self) -> BuildJobRepositoryDiagnostics:
        raise NotImplementedError("PostgreSQL diagnostics are implemented in Task 6.")

    def close(self) -> None:
        with self._close_lock:
            if self._closed:
                return
            self._closed = True
            try:
                self._pool.close()
            except psycopg.Error as error:
                self._raise_unavailable("close", error)

    def _resolve_submit_unique_violation(
        self,
        error: psycopg.errors.UniqueViolation,
        command: SubmitBuildJob,
        key_hash: str,
    ) -> BuildJobSubmission:
        constraint_name = error.diag.constraint_name
        if constraint_name == _IDEMPOTENCY_CONSTRAINT and key_hash:
            return self._read_idempotency_race_owner(command, key_hash)
        if constraint_name == _ACTIVE_CONSTRAINT:
            active = self._read_active_race_owner()
            raise BuildJobConflictError("A build job is already in progress.", active)
        self._raise_unavailable("submit", error)

    def _read_idempotency_race_owner(
        self,
        command: SubmitBuildJob,
        key_hash: str,
    ) -> BuildJobSubmission:
        try:
            with self._pool.connection(timeout=self._pool_timeout_seconds) as connection:
                with connection.transaction():
                    existing = self._lookup_idempotency(connection, key_hash)
                    if existing is None:
                        raise _PersistedDataError
                    return self._idempotent_submission(existing, command)
        except psycopg.Error as error:
            self._raise_unavailable("submit", error)
        except _PersistedDataError as error:
            self._raise_unavailable("submit", error)

    def _read_active_race_owner(self) -> BuildJobSnapshot:
        try:
            with self._pool.connection(timeout=self._pool_timeout_seconds) as connection:
                with connection.transaction():
                    row = connection.execute(_SELECT_ACTIVE_SQL).fetchone()
                    if row is None:
                        raise _PersistedDataError
                    return self._snapshot_from_row(row)
        except psycopg.Error as error:
            self._raise_unavailable("submit", error)
        except _PersistedDataError as error:
            self._raise_unavailable("submit", error)

    @staticmethod
    def _lookup_idempotency(
        connection: psycopg.Connection[tuple[object, ...]],
        key_hash: str,
    ) -> BuildJobSnapshot | None:
        if not key_hash:
            return None
        row = connection.execute(
            _SELECT_IDEMPOTENCY_SQL,
            {"idempotency_key_hash": key_hash},
        ).fetchone()
        return PostgresBuildJobRepository._snapshot_from_row(row) if row is not None else None

    @staticmethod
    def _idempotent_submission(
        existing: BuildJobSnapshot,
        command: SubmitBuildJob,
    ) -> BuildJobSubmission:
        if existing.job_type is not command.job_type:
            raise BuildJobIdempotencyConflictError(
                "Idempotency key conflicts with an existing build job.",
                existing,
            )
        return BuildJobSubmission(BuildJobSubmissionDisposition.REPLAYED, existing)

    def _bounded_limit(self, requested_limit: int | None) -> int:
        resolved_limit = requested_limit or self.settings.list_default_limit
        return max(1, min(int(resolved_limit), self.settings.list_max_limit))

    @staticmethod
    def _snapshot_from_row(row: Sequence[object]) -> BuildJobSnapshot:
        try:
            if len(row) != 19:
                raise _PersistedDataError
            (
                raw_job_id,
                raw_request_id,
                raw_job_type,
                raw_status,
                raw_revision,
                raw_created_at,
                raw_started_at,
                raw_finished_at,
                raw_message,
                raw_error,
                raw_logs,
                raw_result,
                raw_retry_of_job_id,
                raw_idempotency_key_hash,
                raw_worker_id,
                raw_runner_backend,
                raw_lease_token,
                raw_lease_expires_at,
                raw_archived_at,
            ) = row
            job_id = BuildJobId(_required_string(raw_job_id))
            retry_of_job_id = (
                BuildJobId(_required_string(raw_retry_of_job_id))
                if raw_retry_of_job_id is not None
                else None
            )
            worker = _worker_from_values(raw_worker_id, raw_runner_backend)
            _optional_datetime(raw_archived_at)
            return BuildJobSnapshot(
                job_id=job_id,
                request_id=_required_string(raw_request_id),
                job_type=BuildJobType(_required_string(raw_job_type)),
                status=BuildJobStatus(_required_string(raw_status)),
                revision=_positive_integer(raw_revision),
                created_at=_required_datetime(raw_created_at),
                started_at=_optional_datetime(raw_started_at),
                finished_at=_optional_datetime(raw_finished_at),
                message=_required_string(raw_message),
                error=_optional_string_mapping(raw_error),
                logs=_string_tuple(raw_logs),
                result=_optional_json_object(raw_result),
                retry_of_job_id=retry_of_job_id,
                idempotency_key_hash=_required_string(raw_idempotency_key_hash),
                worker=worker,
                lease_token=_required_string(raw_lease_token),
                lease_expires_at=_optional_datetime(raw_lease_expires_at),
            )
        except _PersistedDataError:
            raise
        except (KeyError, TypeError, ValueError):
            raise _PersistedDataError from None

    @staticmethod
    def _snapshot_values(
        snapshot: BuildJobSnapshot,
        *,
        archived_at: datetime | None,
        updated_at: datetime,
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
            Jsonb(dict(snapshot.error)) if snapshot.error is not None else None,
            Jsonb(list(snapshot.logs)),
            Jsonb(dict(snapshot.result)) if snapshot.result is not None else None,
            str(snapshot.retry_of_job_id) if snapshot.retry_of_job_id is not None else None,
            snapshot.idempotency_key_hash,
            worker.worker_id if worker is not None else None,
            worker.runner_backend if worker is not None else None,
            snapshot.lease_token,
            snapshot.lease_expires_at,
            archived_at,
            updated_at,
        )

    @staticmethod
    def _event_values(event: BuildJobEvent) -> tuple[object, ...]:
        serialized = event_to_dict(event)
        return (
            event.event_id,
            str(event.job_id),
            event.revision,
            event.event_type.value,
            event.schema_version,
            event.occurred_at,
            event.request_id,
            Jsonb(serialized["payload"]),
        )

    @staticmethod
    def _event_from_row(row: Sequence[object]) -> BuildJobEvent:
        try:
            if len(row) != 8:
                raise _PersistedDataError
            (
                raw_event_id,
                raw_job_id,
                raw_revision,
                raw_event_type,
                raw_schema_version,
                raw_occurred_at,
                raw_request_id,
                raw_payload,
            ) = row
            if not isinstance(raw_payload, Mapping):
                raise _PersistedDataError
            event = event_from_dict(
                {
                    "event_id": _required_string(raw_event_id),
                    "job_id": _required_string(raw_job_id),
                    "revision": _positive_integer(raw_revision),
                    "event_type": _required_string(raw_event_type),
                    "schema_version": _positive_integer(raw_schema_version),
                    "occurred_at": _required_datetime(raw_occurred_at).isoformat(),
                    "request_id": _required_string(raw_request_id),
                    "payload": raw_payload,
                }
            )
            return event
        except _PersistedDataError:
            raise
        except (KeyError, TypeError, ValueError):
            raise _PersistedDataError from None

    @staticmethod
    def _event_subject_state(row: Sequence[object] | None) -> tuple[bool, bool]:
        if row is None or len(row) != 2 or not all(isinstance(value, bool) for value in row):
            raise _PersistedDataError
        return bool(row[0]), bool(row[1])

    def _close_after_failed_start(self) -> None:
        with self._close_lock:
            if self._closed:
                return
            self._closed = True
            try:
                self._pool.close()
            except Exception:
                pass

    @staticmethod
    def _raise_unavailable(operation: str, error: object) -> Never:
        sqlstate = getattr(error, "sqlstate", None)
        sqlstate_class = sqlstate[:2] if isinstance(sqlstate, str) and len(sqlstate) >= 2 else "XX"
        _LOGGER.error(
            _DATABASE_FAILURE_MESSAGE,
            extra={
                "backend": _BACKEND,
                "operation": operation,
                "sqlstate_class": sqlstate_class,
            },
        )
        raise BuildJobRepositoryUnavailableError(_UNAVAILABLE_MESSAGE) from None


def _required_string(value: object) -> str:
    if not isinstance(value, str):
        raise _PersistedDataError
    return value


def _positive_integer(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise _PersistedDataError
    return value


def _required_datetime(value: object) -> datetime:
    if not isinstance(value, datetime):
        raise _PersistedDataError
    return value


def _optional_datetime(value: object) -> datetime | None:
    if value is None:
        return None
    return _required_datetime(value)


def _optional_string_mapping(value: object) -> dict[str, str] | None:
    if value is None:
        return None
    if not isinstance(value, Mapping) or not all(
        isinstance(key, str) and isinstance(item, str) for key, item in value.items()
    ):
        raise _PersistedDataError
    return dict(value)


def _string_tuple(value: object) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise _PersistedDataError
    return tuple(value)


def _optional_json_object(value: object) -> JsonObject | None:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise _PersistedDataError
    try:
        return coerce_json_object(value)
    except (TypeError, ValueError):
        raise _PersistedDataError from None


def _worker_from_values(worker_id: object, runner_backend: object) -> WorkerIdentity | None:
    if worker_id is None and runner_backend is None:
        return None
    if not isinstance(worker_id, str) or not isinstance(runner_backend, str):
        raise _PersistedDataError
    return WorkerIdentity(worker_id, runner_backend)


__all__ = ["PostgresBuildJobRepository"]

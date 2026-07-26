"""PostgreSQL submission and read operations for the build-job control plane."""

from __future__ import annotations

import logging
import secrets
import threading
from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace
from datetime import datetime, timedelta
from typing import Never

import psycopg
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

from rag_modules.contracts.build_jobs import (
    BuildJobConcurrentUpdateError,
    BuildJobConflictError,
    BuildJobEvent,
    BuildJobEventListQuery,
    BuildJobEventPage,
    BuildJobId,
    BuildJobIdempotencyConflictError,
    BuildJobLease,
    BuildJobLeaseLostError,
    BuildJobListQuery,
    BuildJobNotFoundError,
    BuildJobPage,
    BuildJobRepositoryDiagnostics,
    BuildJobRepositoryError,
    BuildJobRepositorySettings,
    BuildJobRepositoryUnavailableError,
    BuildJobRepositoryWarning,
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
    TERMINAL_STATUSES,
    build_lease,
    claimed_event,
    hash_idempotency_key,
    interrupted_event,
    lease_expires_at,
    new_queued_event,
    validate_idempotency_key,
)

from .schema import PostgresBuildJobSchemaManager

_LOGGER = logging.getLogger(__name__)
_BACKEND = "postgresql"
_DATABASE_FAILURE_MESSAGE = "Build job PostgreSQL repository operation failed."
_POOL_CONNECTION_FAILURE_MESSAGE = "Build job PostgreSQL pool connection failed."
_POOL_CONNECTION_FAILURE_TEMPLATE = "error connecting in %r: %s"
_POOL_LOGGER_NAME = "psycopg.pool"
_UNAVAILABLE_MESSAGE = "Build job repository is unavailable."
_MISSING_POOL_WORKER_STATE = object()

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
_SELECT_CLAIM_SQL = f"""
SELECT {_SNAPSHOT_COLUMNS}
FROM graph_rag_control_plane.build_jobs
WHERE archived_at IS NULL AND status = 'queued'
ORDER BY created_at, job_id
FOR UPDATE SKIP LOCKED
LIMIT 1
"""
_SELECT_JOB_FOR_UPDATE_SQL = f"""
SELECT {_SNAPSHOT_COLUMNS}
FROM graph_rag_control_plane.build_jobs
WHERE job_id = %(job_id)s AND archived_at IS NULL
FOR UPDATE
"""
_UPDATE_SNAPSHOT_SQL = """
UPDATE graph_rag_control_plane.build_jobs
SET status = %(status)s,
    revision = %(revision)s,
    started_at = %(started_at)s,
    finished_at = %(finished_at)s,
    message = %(message)s,
    error = %(error)s,
    logs = %(logs)s,
    result = %(result)s,
    worker_id = %(worker_id)s,
    runner_backend = %(runner_backend)s,
    lease_token = %(lease_token)s,
    lease_expires_at = %(lease_expires_at)s,
    updated_at = %(updated_at)s
WHERE job_id = %(job_id)s
"""
_RENEW_LEASE_SQL = """
UPDATE graph_rag_control_plane.build_jobs
SET lease_expires_at = %(lease_expires_at)s,
    updated_at = %(updated_at)s
WHERE job_id = %(job_id)s
"""
_FIND_DISPATCHABLE_SQL = """
SELECT job_id
FROM graph_rag_control_plane.build_jobs
WHERE archived_at IS NULL AND status = 'queued'
ORDER BY created_at, job_id
LIMIT %(limit)s
"""
_SELECT_EXPIRED_LEASES_SQL = f"""
SELECT {_SNAPSHOT_COLUMNS}
FROM graph_rag_control_plane.build_jobs
WHERE archived_at IS NULL
  AND status IN ('claimed', 'running', 'cancel_requested')
  AND lease_expires_at <= %(now)s
ORDER BY lease_expires_at, job_id
FOR UPDATE SKIP LOCKED
LIMIT %(limit)s
"""
_ARCHIVE_EXCESS_TERMINAL_SQL = """
WITH ranked AS (
    SELECT
        job_id,
        ROW_NUMBER() OVER (
            ORDER BY COALESCE(finished_at, created_at) DESC, job_id DESC
        ) AS retention_rank
    FROM graph_rag_control_plane.build_jobs
    WHERE archived_at IS NULL
      AND status IN ('succeeded', 'failed', 'cancelled', 'interrupted')
)
UPDATE graph_rag_control_plane.build_jobs AS jobs
SET archived_at = %(archived_at)s,
    updated_at = %(archived_at)s
FROM ranked
WHERE jobs.job_id = ranked.job_id
  AND jobs.archived_at IS NULL
  AND ranked.retention_rank > %(retention_limit)s
"""
_SELECT_EXPIRED_ARCHIVE_SQL = """
SELECT job_id
FROM graph_rag_control_plane.build_jobs
WHERE archived_at <= %(cutoff)s
ORDER BY archived_at, job_id
FOR UPDATE SKIP LOCKED
LIMIT %(limit)s
"""
_DELETE_EXPIRED_EVENTS_SQL = """
DELETE FROM graph_rag_control_plane.build_job_events
WHERE job_id = ANY(%(expired_job_ids)s)
"""
_DELETE_EXPIRED_JOBS_SQL = """
DELETE FROM graph_rag_control_plane.build_jobs
WHERE job_id = ANY(%(expired_job_ids)s)
"""

_IDEMPOTENCY_CONSTRAINT = "build_jobs_idempotency_uq"
_ACTIVE_CONSTRAINT = "build_jobs_one_active_uq"
_BATCH_SIZE = 100
_SCHEMA_VERSION = "1"
_LEASE_LOST_MESSAGE = "Build job lease is no longer owned by this worker."
_Now = Callable[[], datetime]


class _PersistedDataError(RuntimeError):
    pass


class _PoolConnectionLogSanitizer(logging.Filter):
    """Sanitize connection errors for registered build-job Psycopg pools."""

    def __init__(self) -> None:
        super().__init__()
        self._lock = threading.Lock()
        self._pool_names: set[str] = set()

    def register(self, pool_name: str) -> None:
        with self._lock:
            self._pool_names.add(pool_name)

    def unregister(self, pool_name: str) -> None:
        with self._lock:
            self._pool_names.discard(pool_name)

    def filter(self, record: logging.LogRecord) -> bool:
        arguments = record.args
        if (
            record.msg != _POOL_CONNECTION_FAILURE_TEMPLATE
            or not isinstance(arguments, tuple)
            or len(arguments) != 2
        ):
            return True
        pool_name = arguments[0]
        with self._lock:
            if not isinstance(pool_name, str) or pool_name not in self._pool_names:
                return True
        error = arguments[1]
        record.msg = _POOL_CONNECTION_FAILURE_MESSAGE
        record.args = ()
        record.exc_info = None
        record.exc_text = None
        record.stack_info = None
        record.backend = _BACKEND
        record.operation = "pool_connect"
        record.sqlstate_class = _sqlstate_class(error)
        return True


_POOL_LOGGER = logging.getLogger(_POOL_LOGGER_NAME)
_POOL_LOG_SANITIZER = _PoolConnectionLogSanitizer()
_POOL_LOGGER.addFilter(_POOL_LOG_SANITIZER)


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
        self._pool_name = f"build-job-{secrets.token_hex(8)}"
        self._pool = ConnectionPool(
            conninfo=dsn,
            min_size=int(pool_min_size),
            max_size=int(pool_max_size),
            name=self._pool_name,
            open=False,
            timeout=self._pool_timeout_seconds,
        )
        _POOL_LOG_SANITIZER.register(self._pool_name)
        self._close_lock = threading.Lock()
        self._closed = False
        try:
            self._pool.open(wait=True, timeout=self._pool_timeout_seconds)
        except psycopg.Error as error:
            self._close_after_failed_start(worker_references=None)
            self._raise_unavailable("open", error)
        try:
            self._schema_manager = PostgresBuildJobSchemaManager(dsn)
            self._schema_manager.verify()
        except BuildJobRepositoryError:
            self._close_after_failed_start(
                worker_references=_capture_pool_worker_references(self._pool)
            )
            raise
        except Exception as error:
            self._close_after_failed_start(
                worker_references=_capture_pool_worker_references(self._pool)
            )
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
                    self._apply_retention(connection, now=event.occurred_at)
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
        try:
            with self._pool.connection(timeout=self._pool_timeout_seconds) as connection:
                with connection.transaction():
                    row = connection.execute(_SELECT_CLAIM_SQL).fetchone()
                    if row is None:
                        return None
                    snapshot = self._snapshot_from_row(row)
                    now = self._now()
                    token = secrets.token_urlsafe(32)
                    expires_at = lease_expires_at(now, self.settings)
                    event = claimed_event(
                        snapshot,
                        worker=worker,
                        lease_token=token,
                        lease_expires_at=expires_at,
                        occurred_at=now,
                    )
                    claimed = reduce_build_job(snapshot, event)
                    connection.execute(_INSERT_EVENT_SQL, self._event_values(event))
                    self._update_snapshot(connection, claimed, updated_at=now)
                    return build_lease(
                        claimed,
                        worker=worker,
                        lease_token=token,
                        lease_expires_at=expires_at,
                    )
        except psycopg.Error as error:
            self._raise_unavailable("claim", error)
        except _PersistedDataError as error:
            self._raise_unavailable("claim", error)

    def renew_lease(self, lease: BuildJobLease) -> BuildJobLease:
        try:
            with self._pool.connection(timeout=self._pool_timeout_seconds) as connection:
                with connection.transaction():
                    row = connection.execute(
                        _SELECT_JOB_FOR_UPDATE_SQL,
                        {"job_id": str(lease.job_id)},
                    ).fetchone()
                    snapshot = self._snapshot_from_row(row) if row is not None else None
                    now = self._now()
                    if snapshot is None or not self._lease_is_current(snapshot, lease, now=now):
                        raise BuildJobLeaseLostError(_LEASE_LOST_MESSAGE)
                    renewed = replace(
                        lease,
                        lease_expires_at=lease_expires_at(now, self.settings),
                    )
                    connection.execute(
                        _RENEW_LEASE_SQL,
                        {
                            "job_id": str(lease.job_id),
                            "lease_expires_at": renewed.lease_expires_at,
                            "updated_at": now,
                        },
                    )
                    return renewed
        except psycopg.Error as error:
            self._raise_unavailable("renew_lease", error)
        except _PersistedDataError as error:
            self._raise_unavailable("renew_lease", error)

    def apply(
        self,
        event: BuildJobEvent,
        *,
        expected_revision: int,
        lease: BuildJobLease | None = None,
    ) -> BuildJobSnapshot:
        try:
            with self._pool.connection(timeout=self._pool_timeout_seconds) as connection:
                with connection.transaction():
                    row = connection.execute(
                        _SELECT_JOB_FOR_UPDATE_SQL,
                        {"job_id": str(event.job_id)},
                    ).fetchone()
                    if row is None:
                        raise BuildJobNotFoundError(event.job_id)
                    snapshot = self._snapshot_from_row(row)
                    if snapshot.revision != expected_revision:
                        raise BuildJobConcurrentUpdateError(
                            f"Expected revision {expected_revision}, found {snapshot.revision}."
                        )
                    now = self._now()
                    if lease is not None and not self._lease_is_current(
                        snapshot,
                        lease,
                        now=now,
                    ):
                        raise BuildJobLeaseLostError(_LEASE_LOST_MESSAGE)
                    updated = reduce_build_job(snapshot, event)
                    connection.execute(_INSERT_EVENT_SQL, self._event_values(event))
                    self._update_snapshot(connection, updated, updated_at=event.occurred_at)
                    if updated.status in TERMINAL_STATUSES:
                        self._apply_retention(connection, now=now)
                    return updated
        except psycopg.Error as error:
            self._raise_unavailable("apply", error)
        except _PersistedDataError as error:
            self._raise_unavailable("apply", error)

    def find_dispatchable(self, *, limit: int) -> tuple[BuildJobId, ...]:
        bounded_limit = max(0, int(limit))
        if bounded_limit == 0:
            return ()
        try:
            with self._pool.connection(timeout=self._pool_timeout_seconds) as connection:
                with connection.transaction():
                    rows = connection.execute(
                        _FIND_DISPATCHABLE_SQL,
                        {"limit": bounded_limit},
                    ).fetchall()
                    return tuple(self._job_id_from_row(row) for row in rows)
        except psycopg.Error as error:
            self._raise_unavailable("find_dispatchable", error)
        except _PersistedDataError as error:
            self._raise_unavailable("find_dispatchable", error)

    def recover_expired_leases(self) -> tuple[BuildJobSnapshot, ...]:
        recovered: list[BuildJobSnapshot] = []
        try:
            with self._pool.connection(timeout=self._pool_timeout_seconds) as connection:
                while True:
                    with connection.transaction():
                        now = self._now()
                        rows = connection.execute(
                            _SELECT_EXPIRED_LEASES_SQL,
                            {"now": now, "limit": _BATCH_SIZE},
                        ).fetchall()
                        snapshots = tuple(self._snapshot_from_row(row) for row in rows)
                        for snapshot in snapshots:
                            self._validate_recoverable_snapshot(snapshot, now=now)
                            event = interrupted_event(snapshot, occurred_at=now)
                            updated = reduce_build_job(snapshot, event)
                            connection.execute(_INSERT_EVENT_SQL, self._event_values(event))
                            self._update_snapshot(connection, updated, updated_at=now)
                            recovered.append(updated)
                        self._apply_retention(connection, now=now)
                    if len(snapshots) < _BATCH_SIZE:
                        return tuple(recovered)
        except psycopg.Error as error:
            self._raise_unavailable("recover_expired_leases", error)
        except _PersistedDataError as error:
            self._raise_unavailable("recover_expired_leases", error)

    def apply_retention(self) -> None:
        try:
            with self._pool.connection(timeout=self._pool_timeout_seconds) as connection:
                with connection.transaction():
                    self._apply_retention(connection, now=self._now())
        except psycopg.Error as error:
            self._raise_unavailable("apply_retention", error)
        except _PersistedDataError as error:
            self._raise_unavailable("apply_retention", error)

    def diagnostics(self) -> BuildJobRepositoryDiagnostics:
        try:
            with self._pool.connection(timeout=self._pool_timeout_seconds) as connection:
                connection.execute("SELECT 1").fetchone()
            self._schema_manager.verify()
        except Exception:
            return BuildJobRepositoryDiagnostics(
                backend=_BACKEND,
                ready=False,
                schema_version=_SCHEMA_VERSION,
                warnings=(
                    BuildJobRepositoryWarning(
                        code="BUILD_JOB_POSTGRES_UNAVAILABLE",
                        component="repository",
                        identifier=_BACKEND,
                        detected_at=self._now().isoformat(),
                    ),
                ),
            )
        return BuildJobRepositoryDiagnostics(
            backend=_BACKEND,
            ready=True,
            schema_version=_SCHEMA_VERSION,
        )

    def close(self) -> None:
        with self._close_lock:
            if self._closed:
                return
            self._closed = True
            worker_references = _capture_pool_worker_references(self._pool)
            try:
                self._pool.close()
            except psycopg.Error as error:
                self._raise_unavailable("close", error)
            finally:
                self._unregister_pool_log_protection_if_stopped(worker_references)

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
    def _lease_is_current(
        snapshot: BuildJobSnapshot,
        lease: BuildJobLease,
        *,
        now: datetime,
    ) -> bool:
        if (
            snapshot.job_id != lease.job_id
            or snapshot.revision != lease.revision
            or snapshot.worker != lease.worker
            or snapshot.status in TERMINAL_STATUSES
            or snapshot.lease_expires_at is None
            or snapshot.lease_expires_at != lease.lease_expires_at
            or snapshot.lease_expires_at <= now
        ):
            return False
        return secrets.compare_digest(snapshot.lease_token, lease.lease_token)

    @staticmethod
    def _validate_recoverable_snapshot(
        snapshot: BuildJobSnapshot,
        *,
        now: datetime,
    ) -> None:
        worker = snapshot.worker
        if (
            snapshot.status
            not in {
                BuildJobStatus.CLAIMED,
                BuildJobStatus.RUNNING,
                BuildJobStatus.CANCEL_REQUESTED,
            }
            or worker is None
            or not worker.worker_id
            or not worker.runner_backend
            or not snapshot.lease_token
            or snapshot.lease_expires_at is None
            or snapshot.lease_expires_at > now
        ):
            raise _PersistedDataError

    @staticmethod
    def _update_snapshot(
        connection: psycopg.Connection[tuple[object, ...]],
        snapshot: BuildJobSnapshot,
        *,
        updated_at: datetime,
    ) -> None:
        worker = snapshot.worker
        connection.execute(
            _UPDATE_SNAPSHOT_SQL,
            {
                "job_id": str(snapshot.job_id),
                "status": snapshot.status.value,
                "revision": snapshot.revision,
                "started_at": snapshot.started_at,
                "finished_at": snapshot.finished_at,
                "message": snapshot.message,
                "error": Jsonb(dict(snapshot.error)) if snapshot.error is not None else None,
                "logs": Jsonb(list(snapshot.logs)),
                "result": Jsonb(dict(snapshot.result)) if snapshot.result is not None else None,
                "worker_id": worker.worker_id if worker is not None else None,
                "runner_backend": worker.runner_backend if worker is not None else None,
                "lease_token": snapshot.lease_token,
                "lease_expires_at": snapshot.lease_expires_at,
                "updated_at": updated_at,
            },
        )

    def _apply_retention(
        self,
        connection: psycopg.Connection[tuple[object, ...]],
        *,
        now: datetime,
    ) -> None:
        connection.execute(
            _ARCHIVE_EXCESS_TERMINAL_SQL,
            {
                "archived_at": now,
                "retention_limit": max(0, int(self.settings.retention_limit)),
            },
        )
        cutoff = now - timedelta(days=int(self.settings.audit_retention_days))
        while True:
            rows = connection.execute(
                _SELECT_EXPIRED_ARCHIVE_SQL,
                {"cutoff": cutoff, "limit": _BATCH_SIZE},
            ).fetchall()
            expired_job_ids = [str(self._job_id_from_row(row)) for row in rows]
            if not expired_job_ids:
                return
            parameters = {"expired_job_ids": expired_job_ids}
            connection.execute(_DELETE_EXPIRED_EVENTS_SQL, parameters)
            connection.execute(_DELETE_EXPIRED_JOBS_SQL, parameters)
            if len(expired_job_ids) < _BATCH_SIZE:
                return

    @staticmethod
    def _job_id_from_row(row: Sequence[object]) -> BuildJobId:
        try:
            if len(row) != 1:
                raise _PersistedDataError
            return BuildJobId(_required_string(row[0]))
        except _PersistedDataError:
            raise
        except (TypeError, ValueError):
            raise _PersistedDataError from None

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

    def _close_after_failed_start(
        self,
        *,
        worker_references: tuple[threading.Thread, ...] | None,
    ) -> None:
        with self._close_lock:
            if self._closed:
                return
            self._closed = True
            try:
                self._pool.close()
            except Exception:
                pass
            finally:
                self._unregister_pool_log_protection_if_stopped(worker_references)

    def _unregister_pool_log_protection_if_stopped(
        self,
        worker_references: tuple[threading.Thread, ...] | None,
    ) -> None:
        if _pool_workers_are_stopped(worker_references):
            _POOL_LOG_SANITIZER.unregister(self._pool_name)

    @staticmethod
    def _raise_unavailable(operation: str, error: object) -> Never:
        _LOGGER.error(
            _DATABASE_FAILURE_MESSAGE,
            extra={
                "backend": _BACKEND,
                "operation": operation,
                "sqlstate_class": _sqlstate_class(error),
            },
        )
        raise BuildJobRepositoryUnavailableError(_UNAVAILABLE_MESSAGE) from None


def _required_string(value: object) -> str:
    if not isinstance(value, str):
        raise _PersistedDataError
    return value


def _sqlstate_class(error: object) -> str:
    sqlstate = getattr(error, "sqlstate", None)
    return sqlstate[:2] if isinstance(sqlstate, str) and len(sqlstate) >= 2 else "XX"


def _capture_pool_worker_references(
    pool: object,
) -> tuple[threading.Thread, ...] | None:
    try:
        workers = getattr(pool, "_workers", _MISSING_POOL_WORKER_STATE)
        scheduler = getattr(pool, "_sched_runner", _MISSING_POOL_WORKER_STATE)
        if workers is _MISSING_POOL_WORKER_STATE or scheduler is _MISSING_POOL_WORKER_STATE:
            return None
        if not isinstance(workers, list):
            return None

        references: list[threading.Thread] = []
        for worker in workers:
            if not isinstance(worker, threading.Thread):
                return None
            references.append(worker)
        if scheduler is not None:
            if not isinstance(scheduler, threading.Thread):
                return None
            references.append(scheduler)
        return tuple(references)
    except Exception:
        return None


def _pool_workers_are_stopped(
    worker_references: tuple[threading.Thread, ...] | None,
) -> bool:
    if worker_references is None:
        return False
    try:
        return all(not worker.is_alive() for worker in worker_references)
    except Exception:
        return False


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

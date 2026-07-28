"""Validated, explicit V3 file import for the PostgreSQL build-job store."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import psycopg

from rag_modules.contracts.build_jobs import (
    BuildJobEvent,
    BuildJobId,
    BuildJobRepositoryError,
    BuildJobRepositoryUnavailableError,
    BuildJobSnapshot,
    BuildJobStatus,
    BuildJobType,
)
from rag_modules.runtime.build_jobs.file_repository_codecs import datetime_from_json
from rag_modules.runtime.build_jobs.file_repository_events import TERMINAL_STATUSES
from rag_modules.runtime.build_jobs.serialization import (
    BUILD_JOB_ENVELOPE_SCHEMA_VERSION,
    BuildJobEnvelope,
    envelope_from_dict,
)

from . import repository as postgres_repository
from .repository import PostgresBuildJobRepository

_SOURCE_INVALID_MESSAGE = "Build job V3 import source is invalid."
_DATABASE_FAILURE_MESSAGE = "Build job PostgreSQL file import failed."
_HASH_PATTERN = re.compile(r"[0-9a-f]{64}\Z")
_IDEMPOTENCY_KEYS = frozenset({"key_hash", "job_id", "job_type", "created_at"})
_ACTIVE_STATUSES = frozenset(
    {
        BuildJobStatus.QUEUED,
        BuildJobStatus.CLAIMED,
        BuildJobStatus.RUNNING,
        BuildJobStatus.CANCEL_REQUESTED,
    }
)

_SELECT_JOB_SQL = f"""
SELECT {postgres_repository._SNAPSHOT_COLUMNS}
FROM graph_rag_control_plane.build_jobs
WHERE job_id = %s
FOR UPDATE
"""
_READ_JOB_SQL = _SELECT_JOB_SQL.removesuffix("FOR UPDATE\n")
_SELECT_EVENTS_SQL = """
SELECT event_id, job_id, revision, event_type, schema_version, occurred_at, request_id, payload
FROM graph_rag_control_plane.build_job_events
WHERE job_id = %s
ORDER BY revision
FOR UPDATE
"""
_READ_EVENTS_SQL = _SELECT_EVENTS_SQL.removesuffix("FOR UPDATE\n")
_SELECT_IDEMPOTENCY_OWNER_SQL = """
SELECT job_id
FROM graph_rag_control_plane.build_jobs
WHERE idempotency_key_hash = %s
FOR UPDATE
"""
_READ_IDEMPOTENCY_OWNER_SQL = _SELECT_IDEMPOTENCY_OWNER_SQL.removesuffix("FOR UPDATE\n")
_SELECT_EVENT_OWNER_SQL = """
SELECT job_id, revision
FROM graph_rag_control_plane.build_job_events
WHERE event_id = %s
FOR UPDATE
"""
_READ_EVENT_OWNER_SQL = _SELECT_EVENT_OWNER_SQL.removesuffix("FOR UPDATE\n")
_SELECT_ACTIVE_OWNER_SQL = """
SELECT job_id
FROM graph_rag_control_plane.build_jobs
WHERE archived_at IS NULL
  AND status IN ('queued', 'claimed', 'running', 'cancel_requested')
FOR UPDATE
"""
_READ_ACTIVE_OWNER_SQL = _SELECT_ACTIVE_OWNER_SQL.removesuffix("FOR UPDATE\n")


@dataclass(frozen=True, slots=True)
class BuildJobImportReport:
    scanned_jobs: int
    scanned_events: int
    imported_jobs: int
    skipped_jobs: int
    conflicts: int
    dry_run: bool


@dataclass(frozen=True, slots=True)
class _SourceJob:
    envelope: BuildJobEnvelope
    archived_at: datetime | None

    @property
    def snapshot(self) -> BuildJobSnapshot:
        return self.envelope.snapshot


class V3BuildJobImporter:
    """Replay a fully validated V3 file repository into one PostgreSQL transaction."""

    def __init__(self, repository: PostgresBuildJobRepository) -> None:
        self._repository = repository

    def run(self, source_path: str | Path, dry_run: bool = False) -> BuildJobImportReport:
        source_jobs = _discover_source(Path(source_path))
        scanned_events = sum(len(source.envelope.events) for source in source_jobs)
        try:
            with self._repository._pool.connection(
                timeout=self._repository._pool_timeout_seconds
            ) as connection:
                with connection.transaction(force_rollback=bool(dry_run)):
                    if dry_run:
                        connection.execute("SET TRANSACTION READ ONLY")
                    missing_job_ids, skipped_jobs = self._preflight(
                        connection,
                        source_jobs,
                        lock=not dry_run,
                    )
                    if not dry_run:
                        self._insert_missing(connection, source_jobs, missing_job_ids)
        except BuildJobRepositoryError:
            raise
        except psycopg.Error:
            raise BuildJobRepositoryUnavailableError(_DATABASE_FAILURE_MESSAGE) from None
        except Exception:
            raise BuildJobRepositoryUnavailableError(_DATABASE_FAILURE_MESSAGE) from None

        return BuildJobImportReport(
            scanned_jobs=len(source_jobs),
            scanned_events=scanned_events,
            imported_jobs=len(missing_job_ids),
            skipped_jobs=skipped_jobs,
            conflicts=0,
            dry_run=bool(dry_run),
        )

    @staticmethod
    def _preflight(
        connection: psycopg.Connection[tuple[object, ...]],
        source_jobs: tuple[_SourceJob, ...],
        *,
        lock: bool,
    ) -> tuple[frozenset[BuildJobId], int]:
        select_active_sql = _SELECT_ACTIVE_OWNER_SQL if lock else _READ_ACTIVE_OWNER_SQL
        select_job_sql = _SELECT_JOB_SQL if lock else _READ_JOB_SQL
        select_events_sql = _SELECT_EVENTS_SQL if lock else _READ_EVENTS_SQL
        source_by_id = {source.snapshot.job_id: source for source in source_jobs}
        active_source = next(
            (
                source
                for source in source_jobs
                if source.archived_at is None and source.snapshot.status in _ACTIVE_STATUSES
            ),
            None,
        )
        if active_source is not None:
            active_rows = connection.execute(select_active_sql).fetchall()
            for active_row in active_rows:
                owner = _job_id_from_owner_row(active_row)
                if owner not in source_by_id:
                    _raise_job_conflict(active_source.snapshot.job_id)

        missing_job_ids: set[BuildJobId] = set()
        skipped_jobs = 0
        for source in source_jobs:
            snapshot = source.snapshot
            V3BuildJobImporter._validate_destination_ownership(
                connection,
                source,
                lock=lock,
            )
            job_row = connection.execute(
                select_job_sql,
                (str(snapshot.job_id),),
            ).fetchone()
            event_rows = connection.execute(
                select_events_sql,
                (str(snapshot.job_id),),
            ).fetchall()
            destination_events = tuple(
                PostgresBuildJobRepository._event_from_row(event_row) for event_row in event_rows
            )

            if job_row is None:
                V3BuildJobImporter._validate_event_id_ownership(
                    connection,
                    source,
                    lock=lock,
                )
                missing_job_ids.add(snapshot.job_id)
                continue

            destination_snapshot = PostgresBuildJobRepository._snapshot_from_row(job_row)
            destination_archived_at = _archived_at_from_row(job_row)
            if destination_snapshot != snapshot or destination_archived_at != source.archived_at:
                _raise_job_conflict(snapshot.job_id)
            _require_matching_events(
                snapshot.job_id,
                source.envelope.events,
                destination_events,
            )
            skipped_jobs += 1
        return frozenset(missing_job_ids), skipped_jobs

    @staticmethod
    def _validate_destination_ownership(
        connection: psycopg.Connection[tuple[object, ...]],
        source: _SourceJob,
        *,
        lock: bool,
    ) -> None:
        key_hash = source.snapshot.idempotency_key_hash
        if not key_hash:
            return
        statement = _SELECT_IDEMPOTENCY_OWNER_SQL if lock else _READ_IDEMPOTENCY_OWNER_SQL
        row = connection.execute(statement, (key_hash,)).fetchone()
        if row is not None and _job_id_from_owner_row(row) != source.snapshot.job_id:
            _raise_job_conflict(source.snapshot.job_id)

    @staticmethod
    def _validate_event_id_ownership(
        connection: psycopg.Connection[tuple[object, ...]],
        source: _SourceJob,
        *,
        lock: bool,
    ) -> None:
        statement = _SELECT_EVENT_OWNER_SQL if lock else _READ_EVENT_OWNER_SQL
        for event in source.envelope.events:
            row = connection.execute(statement, (event.event_id,)).fetchone()
            if row is None:
                continue
            try:
                owner = BuildJobId(str(row[0]))
                raw_revision = row[1]
                if isinstance(raw_revision, bool) or not isinstance(raw_revision, int):
                    raise ValueError
                revision = raw_revision
            except (IndexError, TypeError, ValueError):
                raise BuildJobRepositoryUnavailableError(_DATABASE_FAILURE_MESSAGE) from None
            if owner != source.snapshot.job_id or revision != event.revision:
                _raise_event_conflict(source.snapshot.job_id, event.revision)

    @staticmethod
    def _insert_missing(
        connection: psycopg.Connection[tuple[object, ...]],
        source_jobs: tuple[_SourceJob, ...],
        missing_job_ids: frozenset[BuildJobId],
    ) -> None:
        for source in source_jobs:
            if source.snapshot.job_id not in missing_job_ids:
                continue
            updated_at = source.archived_at or (
                source.envelope.events[-1].occurred_at
                if source.envelope.events
                else source.snapshot.created_at
            )
            try:
                connection.execute(
                    postgres_repository._INSERT_SNAPSHOT_SQL,
                    PostgresBuildJobRepository._snapshot_values(
                        source.snapshot,
                        archived_at=source.archived_at,
                        updated_at=updated_at,
                    ),
                )
                for event in source.envelope.events:
                    connection.execute(
                        postgres_repository._INSERT_EVENT_SQL,
                        PostgresBuildJobRepository._event_values(event),
                    )
            except psycopg.errors.UniqueViolation:
                _raise_job_conflict(source.snapshot.job_id)


def _discover_source(source_path: Path) -> tuple[_SourceJob, ...]:
    try:
        repository_dir = source_path.parent / f"{source_path.stem}.d"
        _validate_metadata(repository_dir / "metadata.json")
        jobs_dir = repository_dir / "jobs"
        archive_dir = repository_dir / "archive"
        idempotency_dir = repository_dir / "idempotency"
        if not all(path.is_dir() for path in (jobs_dir, archive_dir, idempotency_dir)):
            raise ValueError

        active = _load_envelope_directory(jobs_dir, archived=False)
        archived = _load_envelope_directory(archive_dir, archived=True)
        source_jobs = (*active, *archived)
        job_ids = [source.snapshot.job_id for source in source_jobs]
        if len(job_ids) != len(set(job_ids)):
            raise ValueError
        if (
            sum(
                source.archived_at is None and source.snapshot.status in _ACTIVE_STATUSES
                for source in source_jobs
            )
            > 1
        ):
            raise ValueError
        _validate_idempotency_indexes(idempotency_dir, source_jobs)
        return tuple(sorted(source_jobs, key=lambda source: str(source.snapshot.job_id)))
    except BuildJobRepositoryError:
        raise
    except Exception:
        raise BuildJobRepositoryError(_SOURCE_INVALID_MESSAGE) from None


def _validate_metadata(path: Path) -> None:
    payload = _read_json_object(path)
    if set(payload) != {"schema_version"}:
        raise ValueError
    schema_version = payload["schema_version"]
    if (
        isinstance(schema_version, bool)
        or not isinstance(schema_version, int)
        or schema_version != BUILD_JOB_ENVELOPE_SCHEMA_VERSION
    ):
        raise ValueError


def _load_envelope_directory(path: Path, *, archived: bool) -> tuple[_SourceJob, ...]:
    allowed_suffixes = {".json", ".archived-at"} if archived else {".json"}
    if any(
        not entry.is_file() or not any(entry.name.endswith(suffix) for suffix in allowed_suffixes)
        for entry in path.iterdir()
    ):
        raise ValueError

    json_paths = sorted(entry for entry in path.iterdir() if entry.name.endswith(".json"))
    sidecars = {
        entry.name.removesuffix(".archived-at"): entry
        for entry in path.iterdir()
        if entry.name.endswith(".archived-at")
    }
    if archived and set(sidecars) != {entry.stem for entry in json_paths}:
        raise ValueError

    source_jobs: list[_SourceJob] = []
    for envelope_path in json_paths:
        job_id = BuildJobId(envelope_path.stem)
        envelope = envelope_from_dict(_read_json_object(envelope_path))
        if envelope.snapshot.job_id != job_id:
            raise ValueError
        archived_at = None
        if archived:
            if envelope.snapshot.status not in TERMINAL_STATUSES:
                raise ValueError
            archived_at = datetime_from_json(
                sidecars[envelope_path.stem].read_text(encoding="utf-8")
            )
            if archived_at.tzinfo is None:
                raise ValueError
        _validate_snapshot_key_hash(envelope.snapshot)
        source_jobs.append(_SourceJob(envelope=envelope, archived_at=archived_at))
    return tuple(source_jobs)


def _validate_snapshot_key_hash(snapshot: BuildJobSnapshot) -> None:
    key_hash = snapshot.idempotency_key_hash
    if key_hash and _HASH_PATTERN.fullmatch(key_hash) is None:
        raise ValueError


def _validate_idempotency_indexes(
    path: Path,
    source_jobs: Sequence[_SourceJob],
) -> None:
    if any(not entry.is_file() or entry.suffix != ".json" for entry in path.iterdir()):
        raise ValueError
    jobs_by_hash: dict[str, _SourceJob] = {}
    for source in source_jobs:
        key_hash = source.snapshot.idempotency_key_hash
        if not key_hash:
            continue
        if key_hash in jobs_by_hash:
            raise ValueError
        jobs_by_hash[key_hash] = source

    indexes: dict[str, Mapping[str, object]] = {}
    for index_path in path.iterdir():
        payload = _read_json_object(index_path)
        if set(payload) != _IDEMPOTENCY_KEYS or index_path.stem != payload["key_hash"]:
            raise ValueError
        key_hash = str(payload["key_hash"])
        if _HASH_PATTERN.fullmatch(key_hash) is None or key_hash in indexes:
            raise ValueError
        created_at = datetime_from_json(payload["created_at"])
        if created_at.tzinfo is None:
            raise ValueError
        indexes[key_hash] = payload

    if set(indexes) != set(jobs_by_hash):
        raise ValueError
    for key_hash, source in jobs_by_hash.items():
        payload = indexes[key_hash]
        if (
            BuildJobId(str(payload["job_id"])) != source.snapshot.job_id
            or BuildJobType(str(payload["job_type"])) is not source.snapshot.job_type
            or datetime_from_json(payload["created_at"]) != source.snapshot.created_at
        ):
            raise ValueError


def _read_json_object(path: Path) -> Mapping[str, object]:
    with path.open("r", encoding="utf-8") as file:
        payload = json.load(file)
    if not isinstance(payload, Mapping):
        raise ValueError
    return payload


def _job_id_from_owner_row(row: Sequence[object]) -> BuildJobId:
    try:
        if len(row) != 1:
            raise ValueError
        return BuildJobId(str(row[0]))
    except (TypeError, ValueError):
        raise BuildJobRepositoryUnavailableError(_DATABASE_FAILURE_MESSAGE) from None


def _archived_at_from_row(row: Sequence[object]) -> datetime | None:
    if len(row) != 19:
        raise BuildJobRepositoryUnavailableError(_DATABASE_FAILURE_MESSAGE)
    value = row[18]
    if value is not None and not isinstance(value, datetime):
        raise BuildJobRepositoryUnavailableError(_DATABASE_FAILURE_MESSAGE)
    return value


def _require_matching_events(
    job_id: BuildJobId,
    source_events: tuple[BuildJobEvent, ...],
    destination_events: tuple[BuildJobEvent, ...],
) -> None:
    source_by_revision = {event.revision: event for event in source_events}
    destination_by_revision = {event.revision: event for event in destination_events}
    for revision in sorted(set(source_by_revision) | set(destination_by_revision)):
        if source_by_revision.get(revision) != destination_by_revision.get(revision):
            _raise_event_conflict(job_id, revision)


def _raise_job_conflict(job_id: BuildJobId) -> None:
    raise BuildJobRepositoryError(f"Build job import conflict for job {job_id}.")


def _raise_event_conflict(job_id: BuildJobId, revision: int) -> None:
    raise BuildJobRepositoryError(
        f"Build job import conflict for job {job_id} at revision {revision}."
    )


__all__ = ["BuildJobImportReport", "V3BuildJobImporter"]

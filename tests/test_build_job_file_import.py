from __future__ import annotations

import json
from contextlib import AbstractContextManager
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import psycopg
import pytest

from rag_modules.app.build_jobs import (
    BuildJobId,
    BuildJobRepositoryError,
    BuildJobRepositorySettings,
)
from rag_modules.runtime.build_jobs import FileBuildJobRepository
from rag_modules.runtime.build_jobs.postgres import (
    BuildJobImportReport,
    PostgresBuildJobRepository,
    PostgresBuildJobSchemaManager,
    V3BuildJobImporter,
)
from rag_modules.runtime.build_jobs.postgres import importer as postgres_importer
from scripts import build_job_db
from tests.build_job_repository_contract import (
    MutableClock,
    submit_and_succeed,
    submit_build_job,
)

pytest_plugins = ("tests.postgres_build_job_helpers",)

NOW = datetime(2026, 7, 26, 12, 0, tzinfo=timezone.utc)
ARCHIVED_JOB_ID = BuildJobId("a" * 32)
ACTIVE_JOB_ID = BuildJobId("b" * 32)
ARCHIVED_KEY = "archived-import-key"
ACTIVE_KEY = "active-import-key"


class _Rows:
    def fetchone(self) -> tuple[object, ...] | None:
        return None

    def fetchall(self) -> list[tuple[object, ...]]:
        return []


class _Transaction(AbstractContextManager[None]):
    def __init__(self, connection: _ReadOnlyConnection, *, force_rollback: bool) -> None:
        self._connection = connection
        self._force_rollback = force_rollback

    def __enter__(self) -> None:
        self._connection.transaction_force_rollback.append(self._force_rollback)
        return None

    def __exit__(self, _exc_type, _exc, _traceback) -> bool:
        return False


class _ReadOnlyConnection(AbstractContextManager["_ReadOnlyConnection"]):
    def __init__(self) -> None:
        self.statements: list[str] = []
        self.transaction_force_rollback: list[bool] = []

    def __enter__(self) -> _ReadOnlyConnection:
        return self

    def __exit__(self, _exc_type, _exc, _traceback) -> bool:
        return False

    def transaction(self, *, force_rollback: bool) -> _Transaction:
        return _Transaction(self, force_rollback=force_rollback)

    def execute(self, query: object, _params: object = None) -> _Rows:
        statement = str(query)
        self.statements.append(statement)
        assert not statement.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE"))
        assert "FOR UPDATE" not in statement.upper()
        return _Rows()


class _ReadOnlyPool:
    def __init__(self, connection: _ReadOnlyConnection) -> None:
        self._connection = connection
        self.checkout_timeouts: list[float | None] = []

    def connection(self, *, timeout: float | None = None) -> _ReadOnlyConnection:
        self.checkout_timeouts.append(timeout)
        return self._connection


def _create_v3_source(tmp_path: Path) -> Path:
    source_path = tmp_path / "build_jobs.json"
    clock = MutableClock(NOW)
    repository = FileBuildJobRepository(
        str(source_path),
        now=clock.now,
        settings=BuildJobRepositorySettings(retention_limit=0),
    )
    submit_and_succeed(
        repository,
        str(ARCHIVED_JOB_ID),
        clock=clock,
        key=ARCHIVED_KEY,
    )
    repository.apply_retention()
    clock.advance(seconds=1)
    submit_build_job(repository, str(ACTIVE_JOB_ID), key=ACTIVE_KEY)
    return source_path


def _open_importer(dsn: str) -> tuple[V3BuildJobImporter, PostgresBuildJobRepository]:
    PostgresBuildJobSchemaManager(dsn).migrate()
    repository = PostgresBuildJobRepository(
        dsn,
        now=lambda: NOW,
        pool_min_size=1,
        pool_max_size=1,
    )
    return V3BuildJobImporter(repository), repository


def _database_counts(dsn: str) -> tuple[int, int]:
    with psycopg.connect(dsn) as connection:
        jobs = connection.execute(
            "SELECT count(*) FROM graph_rag_control_plane.build_jobs"
        ).fetchone()
        events = connection.execute(
            "SELECT count(*) FROM graph_rag_control_plane.build_job_events"
        ).fetchone()
    assert jobs is not None
    assert events is not None
    return int(jobs[0]), int(events[0])


def _archived_at(dsn: str, job_id: BuildJobId) -> datetime | None:
    with psycopg.connect(dsn) as connection:
        row = connection.execute(
            """
            SELECT archived_at
            FROM graph_rag_control_plane.build_jobs
            WHERE job_id = %s
            """,
            (str(job_id),),
        ).fetchone()
    assert row is not None
    return row[0] if isinstance(row[0], datetime) else None


def _event_revisions(dsn: str, job_id: BuildJobId) -> tuple[int, ...]:
    with psycopg.connect(dsn) as connection:
        rows = connection.execute(
            """
            SELECT revision
            FROM graph_rag_control_plane.build_job_events
            WHERE job_id = %s
            ORDER BY revision
            """,
            (str(job_id),),
        ).fetchall()
    return tuple(int(row[0]) for row in rows)


def _assert_invalid_before_checkout(source_path: Path) -> None:
    pool = Mock()
    repository = SimpleNamespace(_pool=pool, _pool_timeout_seconds=1.0)

    with pytest.raises(
        BuildJobRepositoryError,
        match=r"^Build job V3 import source is invalid\.$",
    ):
        V3BuildJobImporter(repository).run(source_path, dry_run=True)

    pool.connection.assert_not_called()


def test_dry_run_uses_a_read_only_rollback_transaction(tmp_path: Path) -> None:
    source_path = _create_v3_source(tmp_path)
    connection = _ReadOnlyConnection()
    pool = _ReadOnlyPool(connection)
    repository = SimpleNamespace(_pool=pool, _pool_timeout_seconds=2.0)

    report = V3BuildJobImporter(repository).run(source_path, dry_run=True)

    assert report.scanned_jobs == 2
    assert report.scanned_events == 5
    assert report.imported_jobs == 2
    assert report.dry_run
    assert connection.transaction_force_rollback == [True]
    assert connection.statements[0] == "SET TRANSACTION READ ONLY"
    assert pool.checkout_timeouts == [2.0]


def test_dry_run_validates_active_and_archive_without_writes(
    tmp_path: Path,
    postgres_dsn: str,
) -> None:
    source_path = _create_v3_source(tmp_path)
    importer, repository = _open_importer(postgres_dsn)
    try:
        report = importer.run(source_path, dry_run=True)
    finally:
        repository.close()

    assert report == BuildJobImportReport(
        scanned_jobs=2,
        scanned_events=5,
        imported_jobs=2,
        skipped_jobs=0,
        conflicts=0,
        dry_run=True,
    )
    assert _database_counts(postgres_dsn) == (0, 0)


def test_exact_replay_is_repeatable_and_preserves_archive_timestamp(
    tmp_path: Path,
    postgres_dsn: str,
) -> None:
    source_path = _create_v3_source(tmp_path)
    source_archived_at = datetime.fromisoformat(
        (tmp_path / "build_jobs.d" / "archive" / f"{ARCHIVED_JOB_ID}.archived-at").read_text(
            encoding="utf-8"
        )
    )
    importer, repository = _open_importer(postgres_dsn)
    try:
        first = importer.run(source_path, dry_run=False)
        second = importer.run(source_path, dry_run=False)
    finally:
        repository.close()

    assert first.imported_jobs == 2
    assert first.skipped_jobs == 0
    assert second.imported_jobs == 0
    assert second.skipped_jobs == 2
    assert _database_counts(postgres_dsn) == (2, 5)
    assert _event_revisions(postgres_dsn, ARCHIVED_JOB_ID) == (1, 2, 3, 4)
    assert _archived_at(postgres_dsn, ARCHIVED_JOB_ID) == source_archived_at
    assert _archived_at(postgres_dsn, ACTIVE_JOB_ID) is None


@pytest.mark.parametrize("destination_corruption", ["projection", "event"])
def test_destination_mismatch_fails_closed_without_partial_writes(
    tmp_path: Path,
    postgres_dsn: str,
    destination_corruption: str,
) -> None:
    source_path = _create_v3_source(tmp_path)
    importer, repository = _open_importer(postgres_dsn)
    try:
        importer.run(source_path, dry_run=False)
        with psycopg.connect(postgres_dsn) as connection:
            if destination_corruption == "projection":
                connection.execute(
                    """
                    UPDATE graph_rag_control_plane.build_jobs
                    SET message = %s
                    WHERE job_id = %s
                    """,
                    ("destination-only-message", str(ACTIVE_JOB_ID)),
                )
            else:
                connection.execute(
                    """
                    UPDATE graph_rag_control_plane.build_job_events
                    SET payload = %s
                    WHERE job_id = %s AND revision = 1
                    """,
                    (psycopg.types.json.Jsonb({"destination": "mismatch"}), str(ACTIVE_JOB_ID)),
                )
        before = _database_counts(postgres_dsn)

        with pytest.raises(
            BuildJobRepositoryError,
            match=rf"^Build job import conflict for job {ACTIVE_JOB_ID}( at revision 1)?\.$",
        ):
            importer.run(source_path, dry_run=False)
    finally:
        repository.close()

    assert _database_counts(postgres_dsn) == before


def test_idempotency_owner_conflict_is_detected_before_any_import(
    tmp_path: Path,
    postgres_dsn: str,
) -> None:
    source_path = _create_v3_source(tmp_path)
    source_payload = json.loads(
        (tmp_path / "build_jobs.d" / "jobs" / f"{ACTIVE_JOB_ID}.json").read_text(encoding="utf-8")
    )
    key_hash = source_payload["snapshot"]["idempotency_key_hash"]
    importer, repository = _open_importer(postgres_dsn)
    try:
        with psycopg.connect(postgres_dsn) as connection:
            connection.execute(
                """
                INSERT INTO graph_rag_control_plane.build_jobs (
                    job_id, request_id, job_type, status, revision,
                    created_at, message, logs, idempotency_key_hash,
                    lease_token, updated_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    "c" * 32,
                    "foreign-request",
                    "build",
                    "succeeded",
                    1,
                    NOW,
                    "",
                    psycopg.types.json.Jsonb([]),
                    key_hash,
                    "",
                    NOW,
                ),
            )
        before = _database_counts(postgres_dsn)

        with pytest.raises(
            BuildJobRepositoryError,
            match=rf"^Build job import conflict for job {ACTIVE_JOB_ID}\.$",
        ):
            importer.run(source_path, dry_run=False)
    finally:
        repository.close()

    assert _database_counts(postgres_dsn) == before


def test_idempotency_index_timestamp_is_independent_of_snapshot_and_migration_time(
    tmp_path: Path,
) -> None:
    source_path = tmp_path / "build_jobs.json"
    clock = MutableClock(NOW)

    def advancing_now() -> datetime:
        current = clock.now()
        clock.advance(seconds=1)
        return current

    repository = FileBuildJobRepository(
        str(source_path),
        now=advancing_now,
        settings=BuildJobRepositorySettings(retention_limit=0),
    )
    submit_build_job(repository, str(ACTIVE_JOB_ID), key=ACTIVE_KEY)
    job_payload = json.loads(
        (tmp_path / "build_jobs.d" / "jobs" / f"{ACTIVE_JOB_ID}.json").read_text(encoding="utf-8")
    )
    key_hash = job_payload["snapshot"]["idempotency_key_hash"]
    index_path = tmp_path / "build_jobs.d" / "idempotency" / f"{key_hash}.json"
    index_payload = json.loads(index_path.read_text(encoding="utf-8"))
    assert index_payload["created_at"] != job_payload["snapshot"]["created_at"]
    index_payload["created_at"] = "2000-01-01T00:00:00+00:00"
    index_path.write_text(json.dumps(index_payload), encoding="utf-8")
    connection = _ReadOnlyConnection()

    report = V3BuildJobImporter(
        SimpleNamespace(_pool=_ReadOnlyPool(connection), _pool_timeout_seconds=1.0)
    ).run(source_path, dry_run=True)

    assert report.scanned_jobs == 1
    assert report.imported_jobs == 1


def test_duplicate_event_id_across_source_jobs_fails_before_database_checkout(
    tmp_path: Path,
) -> None:
    source_path = _create_v3_source(tmp_path)
    archived_path = tmp_path / "build_jobs.d" / "archive" / f"{ARCHIVED_JOB_ID}.json"
    active_path = tmp_path / "build_jobs.d" / "jobs" / f"{ACTIVE_JOB_ID}.json"
    archived_payload = json.loads(archived_path.read_text(encoding="utf-8"))
    active_payload = json.loads(active_path.read_text(encoding="utf-8"))
    active_payload["events"][0]["event_id"] = archived_payload["events"][0]["event_id"]
    active_path.write_text(json.dumps(active_payload), encoding="utf-8")

    _assert_invalid_before_checkout(source_path)


@pytest.mark.parametrize(
    "field",
    ["created_at", "started_at", "finished_at", "lease_expires_at"],
)
def test_naive_snapshot_or_baseline_datetime_fails_before_database_checkout(
    tmp_path: Path,
    field: str,
) -> None:
    source_path = _create_v3_source(tmp_path)
    archive_path = tmp_path / "build_jobs.d" / "archive" / f"{ARCHIVED_JOB_ID}.json"
    payload = json.loads(archive_path.read_text(encoding="utf-8"))
    payload["baseline"] = dict(payload["snapshot"])
    payload["events"] = []
    payload["snapshot"][field] = "2026-07-26T12:00:00"
    payload["baseline"][field] = "2026-07-26T12:00:00"
    archive_path.write_text(json.dumps(payload), encoding="utf-8")

    _assert_invalid_before_checkout(source_path)


@pytest.mark.parametrize("target", ["event", "claimed_payload", "archive", "idempotency"])
def test_naive_event_and_auxiliary_datetimes_fail_before_database_checkout(
    tmp_path: Path,
    target: str,
) -> None:
    source_path = _create_v3_source(tmp_path)
    archive_path = tmp_path / "build_jobs.d" / "archive" / f"{ARCHIVED_JOB_ID}.json"
    archive_payload = json.loads(archive_path.read_text(encoding="utf-8"))
    if target == "event":
        archive_payload["events"][0]["occurred_at"] = "2026-07-26T12:00:00"
        archive_path.write_text(json.dumps(archive_payload), encoding="utf-8")
    elif target == "claimed_payload":
        archive_payload["events"][1]["payload"]["lease_expires_at"] = "2026-07-26T12:00:00"
        archive_path.write_text(json.dumps(archive_payload), encoding="utf-8")
    elif target == "archive":
        (tmp_path / "build_jobs.d" / "archive" / f"{ARCHIVED_JOB_ID}.archived-at").write_text(
            "2026-07-26T12:00:00",
            encoding="utf-8",
        )
    else:
        key_hash = archive_payload["snapshot"]["idempotency_key_hash"]
        index_path = tmp_path / "build_jobs.d" / "idempotency" / f"{key_hash}.json"
        index_payload = json.loads(index_path.read_text(encoding="utf-8"))
        index_payload["created_at"] = "2026-07-26T12:00:00"
        index_path.write_text(json.dumps(index_payload), encoding="utf-8")

    _assert_invalid_before_checkout(source_path)


@pytest.mark.parametrize("case", ["baseline_zero", "no_events", "uppercase_stem"])
def test_noncanonical_layout_or_invalid_revisions_fail_before_database_checkout(
    tmp_path: Path,
    case: str,
) -> None:
    source_path = _create_v3_source(tmp_path)
    active_path = tmp_path / "build_jobs.d" / "jobs" / f"{ACTIVE_JOB_ID}.json"
    payload = json.loads(active_path.read_text(encoding="utf-8"))
    if case == "baseline_zero":
        payload["baseline"] = dict(payload["snapshot"])
        payload["baseline"]["revision"] = 0
        payload["events"] = []
        active_path.write_text(json.dumps(payload), encoding="utf-8")
    elif case == "no_events":
        payload["events"] = []
        active_path.write_text(json.dumps(payload), encoding="utf-8")
    else:
        active_path.rename(active_path.with_name(f"{str(ACTIVE_JOB_ID).upper()}.json"))

    _assert_invalid_before_checkout(source_path)


class _UniqueViolationConnection:
    def __init__(self, *, on_event: bool) -> None:
        self._on_event = on_event

    def execute(self, query: object, _params: object = None) -> None:
        statement = str(query)
        if ("build_job_events" in statement) is self._on_event:
            raise psycopg.errors.UniqueViolation
        return None


@pytest.mark.parametrize("on_event", [False, True])
def test_insert_unique_violation_uses_contextual_safe_conflict(
    tmp_path: Path,
    on_event: bool,
) -> None:
    source = postgres_importer._discover_source(_create_v3_source(tmp_path))[0]
    expected = (
        rf"^Build job import conflict for job {source.snapshot.job_id} at revision "
        rf"{source.envelope.events[0].revision}\.$"
        if on_event
        else rf"^Build job import conflict for job {source.snapshot.job_id}\.$"
    )

    with pytest.raises(BuildJobRepositoryError, match=expected):
        V3BuildJobImporter._insert_missing(
            _UniqueViolationConnection(on_event=on_event),
            (source,),
            frozenset({source.snapshot.job_id}),
        )


@pytest.mark.parametrize(
    ("relative_path", "replacement"),
    [
        ("metadata.json", '{"schema_version": 2}'),
        (
            f"jobs/{ACTIVE_JOB_ID}.json",
            '{"schema_version":3,"revision":1,"baseline":null,"snapshot":{},"events":[]}',
        ),
        (f"archive/{ARCHIVED_JOB_ID}.archived-at", "not-a-timestamp"),
        (
            f"idempotency/{'0' * 64}.json",
            '{"key_hash":"mismatch","job_id":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",'
            '"job_type":"build","created_at":"2026-07-26T12:00:00+00:00"}',
        ),
    ],
)
def test_corrupt_source_fails_before_database_checkout(
    tmp_path: Path,
    relative_path: str,
    replacement: str,
) -> None:
    source_path = _create_v3_source(tmp_path)
    target = tmp_path / "build_jobs.d" / relative_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(replacement, encoding="utf-8")
    pool = Mock()
    repository = SimpleNamespace(_pool=pool, _pool_timeout_seconds=1.0)
    importer = V3BuildJobImporter(repository)

    with pytest.raises(
        BuildJobRepositoryError,
        match=r"^Build job V3 import source is invalid\.$",
    ):
        importer.run(source_path, dry_run=True)

    pool.connection.assert_not_called()


def test_cli_import_file_prints_json_counts_and_closes_repository(
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    source_path = tmp_path / "private-source.json"
    config = SimpleNamespace(
        storage=SimpleNamespace(build_job_postgres_dsn="postgresql://configured.invalid/jobs"),
        api=SimpleNamespace(
            build_job_postgres_pool_min_size=1,
            build_job_postgres_pool_max_size=2,
            build_job_postgres_pool_timeout_seconds=3.0,
        ),
    )
    report = BuildJobImportReport(2, 5, 2, 0, 0, True)
    repository = Mock()
    importer = Mock()
    importer.run.return_value = report
    with (
        patch.object(build_job_db, "load_config", return_value=config),
        patch.object(
            build_job_db,
            "PostgresBuildJobRepository",
            return_value=repository,
        ) as repository_type,
        patch.object(build_job_db, "V3BuildJobImporter", return_value=importer),
    ):
        exit_code = build_job_db.main(
            ["import-file", "--source", str(source_path), "--dry-run", "--json"]
        )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.err == ""
    assert json.loads(captured.out) == {
        "conflicts": 0,
        "dry_run": True,
        "imported_jobs": 2,
        "scanned_events": 5,
        "scanned_jobs": 2,
        "skipped_jobs": 0,
    }
    repository_type.assert_called_once_with(
        "postgresql://configured.invalid/jobs",
        now=build_job_db._utc_now,
        pool_min_size=1,
        pool_max_size=2,
        pool_timeout_seconds=3.0,
    )
    importer.run.assert_called_once_with(source_path, dry_run=True)
    repository.close.assert_called_once_with()


def test_cli_import_failure_is_sanitized(
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    source_path = tmp_path / "private-source.json"
    secret_dsn = "postgresql://user:secret@configured.invalid/jobs"
    config = SimpleNamespace(
        storage=SimpleNamespace(build_job_postgres_dsn=secret_dsn),
        api=SimpleNamespace(
            build_job_postgres_pool_min_size=1,
            build_job_postgres_pool_max_size=1,
            build_job_postgres_pool_timeout_seconds=1.0,
        ),
    )
    repository = Mock()
    importer = Mock()
    importer.run.side_effect = RuntimeError(f"dsn={secret_dsn} SQL=SELECT payload='raw-token'")
    with (
        patch.object(build_job_db, "load_config", return_value=config),
        patch.object(build_job_db, "PostgresBuildJobRepository", return_value=repository),
        patch.object(build_job_db, "V3BuildJobImporter", return_value=importer),
    ):
        exit_code = build_job_db.main(["import-file", "--source", str(source_path), "--json"])

    output = capsys.readouterr().out
    assert exit_code == 1
    assert json.loads(output) == {
        "error": "Build job PostgreSQL file import failed.",
        "ready": False,
    }
    assert secret_dsn not in output
    assert "secret" not in output
    assert "SELECT" not in output
    assert "raw-token" not in output
    assert str(source_path) not in output
    repository.close.assert_called_once_with()

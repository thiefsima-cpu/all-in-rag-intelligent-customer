from __future__ import annotations

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import psycopg
import pytest
from psycopg.types.json import Jsonb

from rag_modules.contracts.build_jobs import BuildJobRepositoryError
from rag_modules.runtime.build_jobs.postgres import (
    BuildJobPostgresSchemaStatus,
    PostgresBuildJobSchemaManager,
)
from scripts import build_job_db

pytest_plugins = ("tests.postgres_build_job_helpers",)
CONTROL_PLANE_SCHEMA = "graph_rag_control_plane"


class _Rows:
    def __init__(self, rows: list[tuple[object, ...]]) -> None:
        self._rows = rows

    def fetchone(self) -> tuple[object, ...] | None:
        return self._rows[0] if self._rows else None

    def fetchall(self) -> list[tuple[object, ...]]:
        return list(self._rows)


class _StatusConnection:
    def __init__(
        self,
        *,
        ledger_exists: bool,
        applied: list[tuple[object, ...]] | None = None,
        server_version: int = 160000,
    ) -> None:
        self.info = SimpleNamespace(server_version=server_version)
        self.ledger_exists = ledger_exists
        self.applied = applied or []
        self.statements: list[str] = []

    def __enter__(self) -> _StatusConnection:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def execute(self, query: object, _params: object = None) -> _Rows:
        statement = str(query)
        self.statements.append(statement)
        if "to_regclass" in statement:
            return _Rows([(self.ledger_exists,)])
        if "schema_migrations" in statement:
            return _Rows(self.applied)
        raise AssertionError(f"Unexpected status query: {statement}")


def test_packaged_migrations_are_discovered_with_sha256_checksums() -> None:
    manager = PostgresBuildJobSchemaManager("postgresql://unit-test.invalid/build_jobs")

    assert [(migration.version, migration.name) for migration in manager._migrations] == [
        (1, "build_job_control_plane"),
        (2, "imported_baseline_audit"),
    ]
    assert all(
        migration.checksum == hashlib.sha256(migration.sql.encode("utf-8")).hexdigest()
        for migration in manager._migrations
    )


def test_migration_discovery_sanitizes_resource_errors() -> None:
    with (
        patch(
            "rag_modules.runtime.build_jobs.postgres.schema.resources.files",
            side_effect=OSError("private package path"),
        ),
        pytest.raises(BuildJobRepositoryError) as caught,
    ):
        PostgresBuildJobSchemaManager("postgresql://unit-test.invalid/build_jobs")

    assert str(caught.value) == "Build job PostgreSQL migration resources are unavailable."
    assert "private package path" not in str(caught.value)


def test_status_reports_version_zero_without_executing_ddl() -> None:
    connection = _StatusConnection(ledger_exists=False)
    with patch(
        "rag_modules.runtime.build_jobs.postgres.schema.psycopg.connect",
        return_value=connection,
    ):
        status = PostgresBuildJobSchemaManager("postgresql://unit-test.invalid/build_jobs").status()

    assert status == BuildJobPostgresSchemaStatus(
        current_version=0,
        required_version=2,
        pending_versions=(1, 2),
        ready=False,
    )
    assert connection.statements
    assert all(
        statement.lstrip().upper().startswith("SELECT") for statement in connection.statements
    )


def test_status_rejects_postgresql_older_than_version_16_without_leaking_dsn() -> None:
    dsn = "postgresql://user:secret@unit-test.invalid/build_jobs"
    connection = _StatusConnection(ledger_exists=False, server_version=150000)
    with (
        patch(
            "rag_modules.runtime.build_jobs.postgres.schema.psycopg.connect",
            return_value=connection,
        ),
        pytest.raises(BuildJobRepositoryError) as caught,
    ):
        PostgresBuildJobSchemaManager(dsn).status()

    assert "PostgreSQL server version is unsupported" in str(caught.value)
    assert dsn not in str(caught.value)
    assert "secret" not in str(caught.value)


def test_verify_fails_closed_when_a_recorded_checksum_differs() -> None:
    manager = PostgresBuildJobSchemaManager("postgresql://unit-test.invalid/build_jobs")
    connection = _StatusConnection(ledger_exists=True, applied=[(1, "0" * 64)])
    with (
        patch(
            "rag_modules.runtime.build_jobs.postgres.schema.psycopg.connect",
            return_value=connection,
        ),
        pytest.raises(
            BuildJobRepositoryError,
            match=r"^Build job PostgreSQL schema is not ready\.$",
        ),
    ):
        manager.verify()


def test_cli_status_json_returns_one_when_schema_is_not_ready(
    capsys: pytest.CaptureFixture[str],
) -> None:
    config = SimpleNamespace(
        storage=SimpleNamespace(build_job_postgres_dsn="postgresql://configured.invalid/jobs")
    )
    manager = Mock()
    manager.status.return_value = BuildJobPostgresSchemaStatus(
        current_version=0,
        required_version=1,
        pending_versions=(1,),
        ready=False,
    )
    with (
        patch.object(build_job_db, "load_config", return_value=config),
        patch.object(build_job_db, "PostgresBuildJobSchemaManager", return_value=manager),
    ):
        exit_code = build_job_db.main(["status", "--json"])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert captured.err == ""
    assert json.loads(captured.out) == {
        "current_version": 0,
        "pending_versions": [1],
        "ready": False,
        "required_version": 1,
    }


def test_cli_migrate_returns_zero_and_human_output_without_json(
    capsys: pytest.CaptureFixture[str],
) -> None:
    config = SimpleNamespace(
        storage=SimpleNamespace(build_job_postgres_dsn="postgresql://configured.invalid/jobs")
    )
    manager = Mock()
    manager.migrate.return_value = BuildJobPostgresSchemaStatus(
        current_version=1,
        required_version=1,
        pending_versions=(),
        ready=True,
    )
    with (
        patch.object(build_job_db, "load_config", return_value=config),
        patch.object(build_job_db, "PostgresBuildJobSchemaManager", return_value=manager),
    ):
        exit_code = build_job_db.main(["migrate"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.err == ""
    assert "ready=True" in captured.out
    with pytest.raises(json.JSONDecodeError):
        json.loads(captured.out)


def test_cli_sanitizes_unexpected_database_errors(
    capsys: pytest.CaptureFixture[str],
) -> None:
    secret_dsn = "postgresql://user:secret@configured.invalid/jobs"
    config = SimpleNamespace(storage=SimpleNamespace(build_job_postgres_dsn=secret_dsn))
    manager = Mock()
    manager.status.side_effect = RuntimeError(
        f"password=secret dsn={secret_dsn} SQL=SELECT 1 params=('private',)"
    )
    with (
        patch.object(build_job_db, "load_config", return_value=config),
        patch.object(build_job_db, "PostgresBuildJobSchemaManager", return_value=manager),
    ):
        exit_code = build_job_db.main(["status", "--json"])

    output = capsys.readouterr().out
    assert exit_code == 1
    assert json.loads(output) == {
        "error": "Build job PostgreSQL schema operation failed.",
        "ready": False,
    }
    assert secret_dsn not in output
    assert "secret" not in output
    assert "SELECT" not in output
    assert "private" not in output


@pytest.mark.parametrize("command", ["status", "migrate", "import-file"])
@pytest.mark.parametrize("dsn_case", ["missing", "empty", "whitespace"])
@pytest.mark.parametrize("as_json", [False, True])
def test_cli_rejects_unconfigured_dsn_before_database_object_construction(
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    command: str,
    dsn_case: str,
    as_json: bool,
) -> None:
    storage = (
        SimpleNamespace()
        if dsn_case == "missing"
        else SimpleNamespace(build_job_postgres_dsn="" if dsn_case == "empty" else " \t\r\n ")
    )
    config = SimpleNamespace(
        storage=storage,
        api=SimpleNamespace(
            build_job_postgres_pool_min_size=1,
            build_job_postgres_pool_max_size=2,
            build_job_postgres_pool_timeout_seconds=3.0,
        ),
    )
    argv = [command]
    if command == "import-file":
        argv.extend(["--source", str(tmp_path / "private-source.json")])
    if as_json:
        argv.append("--json")
    with (
        patch.object(build_job_db, "load_config", return_value=config),
        patch.object(build_job_db, "PostgresBuildJobSchemaManager") as manager_type,
        patch.object(build_job_db, "PostgresBuildJobRepository") as repository_type,
        patch.object(build_job_db, "V3BuildJobImporter") as importer_type,
    ):
        exit_code = build_job_db.main(argv)

    captured = capsys.readouterr()
    expected_error = (
        "Build job PostgreSQL file import failed."
        if command == "import-file"
        else "Build job PostgreSQL schema operation failed."
    )
    assert exit_code == 1
    assert captured.err == ""
    if as_json:
        assert json.loads(captured.out) == {"error": expected_error, "ready": False}
    else:
        assert captured.out == f"{expected_error}\n"
    manager_type.assert_not_called()
    repository_type.assert_not_called()
    importer_type.assert_not_called()


def test_status_on_empty_database_does_not_create_schema(postgres_dsn: str) -> None:
    status = PostgresBuildJobSchemaManager(postgres_dsn).status()

    assert status.current_version == 0
    assert status.pending_versions == (1, 2)
    with psycopg.connect(postgres_dsn) as connection:
        row = connection.execute(
            "SELECT to_regnamespace(%s) IS NOT NULL",
            (CONTROL_PLANE_SCHEMA,),
        ).fetchone()
    assert row == (False,)


def test_migrate_is_repeatable_and_verify_succeeds(postgres_dsn: str) -> None:
    manager = PostgresBuildJobSchemaManager(postgres_dsn)

    first = manager.migrate()
    second = manager.migrate()

    assert first.ready
    assert first.current_version == 2
    assert second.current_version == 2
    assert second.pending_versions == ()
    assert manager.verify() == second


def test_modified_loaded_checksum_makes_verify_fail(postgres_dsn: str) -> None:
    manager = PostgresBuildJobSchemaManager(postgres_dsn)
    manager.migrate()
    manager._migrations = (replace(manager._migrations[0], checksum="0" * 64),)

    with pytest.raises(
        BuildJobRepositoryError,
        match=r"^Build job PostgreSQL schema is not ready\.$",
    ):
        manager.verify()


def test_concurrent_migrations_serialize_and_record_one_ledger_row(
    postgres_dsn: str,
) -> None:
    def migrate_once() -> BuildJobPostgresSchemaStatus:
        return PostgresBuildJobSchemaManager(postgres_dsn).migrate()

    with ThreadPoolExecutor(max_workers=2) as executor:
        statuses = list(executor.map(lambda _index: migrate_once(), range(2)))

    assert all(status.ready for status in statuses)
    with psycopg.connect(postgres_dsn) as connection:
        row = connection.execute(
            "SELECT count(*) FROM graph_rag_control_plane.schema_migrations"
        ).fetchone()
    assert row == (2,)


def test_migration_enforces_constraints_and_installs_keyset_indexes(
    postgres_dsn: str,
) -> None:
    PostgresBuildJobSchemaManager(postgres_dsn).migrate()

    with psycopg.connect(postgres_dsn, autocommit=True) as connection:
        with pytest.raises(psycopg.errors.CheckViolation):
            with connection.transaction():
                connection.execute(
                    """
                    INSERT INTO graph_rag_control_plane.build_jobs (
                        job_id, request_id, job_type, status, revision, created_at, updated_at
                    ) VALUES (%s, %s, %s, %s, %s, now(), now())
                    """,
                    ("not-a-job-id", "request-1", "build", "queued", 1),
                )
        with connection.transaction():
            connection.execute(
                """
                INSERT INTO graph_rag_control_plane.build_jobs (
                    job_id, request_id, job_type, status, revision,
                    created_at, updated_at, import_source_schema_version
                ) VALUES (%s, %s, %s, %s, 0, now(), now(), 2)
                """,
                ("c" * 32, "request-v2", "build", "succeeded"),
            )
            connection.execute(
                """
                INSERT INTO graph_rag_control_plane.build_job_events (
                    job_id, revision, event_id, event_type, schema_version,
                    occurred_at, request_id, payload
                ) VALUES (%s, 0, %s, 'baseline_imported', 1, now(), %s, %s)
                """,
                (
                    "c" * 32,
                    f"{'c' * 32}:baseline:0",
                    "request-v2",
                    Jsonb({"source_schema_version": 2}),
                ),
            )
        with pytest.raises(psycopg.errors.CheckViolation):
            with connection.transaction():
                connection.execute(
                    """
                    INSERT INTO graph_rag_control_plane.build_jobs (
                        job_id, request_id, job_type, status, revision, created_at, updated_at
                    ) VALUES (%s, %s, %s, %s, 0, now(), now())
                    """,
                    ("d" * 32, "request-invalid", "build", "succeeded"),
                )
        rows = connection.execute(
            """
            SELECT indexname
            FROM pg_catalog.pg_indexes
            WHERE schemaname = %s
            """,
            (CONTROL_PLANE_SCHEMA,),
        ).fetchall()

    index_names = {row[0] for row in rows}
    assert {
        "build_jobs_list_idx",
        "build_jobs_status_list_idx",
        "build_job_events_list_idx",
    } <= index_names


def _plan_index_names(value: object) -> set[str]:
    if isinstance(value, dict):
        names = {name} if isinstance((name := value.get("Index Name")), str) else set()
        for nested in value.values():
            names.update(_plan_index_names(nested))
        return names
    if isinstance(value, list):
        names: set[str] = set()
        for nested in value:
            names.update(_plan_index_names(nested))
        return names
    return set()


def test_migration_indexes_are_compatible_with_control_plane_queries(
    postgres_dsn: str,
) -> None:
    PostgresBuildJobSchemaManager(postgres_dsn).migrate()
    cases: tuple[tuple[str, str, tuple[object, ...]], ...] = (
        (
            "build_jobs_idempotency_uq",
            """
            SELECT job_id
            FROM graph_rag_control_plane.build_jobs
            WHERE idempotency_key_hash = %s
            """,
            ("a" * 64,),
        ),
        (
            "build_jobs_one_active_uq",
            """
            SELECT job_id
            FROM graph_rag_control_plane.build_jobs
            WHERE archived_at IS NULL
              AND status IN ('queued', 'claimed', 'running', 'cancel_requested')
            """,
            (),
        ),
        (
            "build_jobs_list_idx",
            """
            SELECT job_id
            FROM graph_rag_control_plane.build_jobs
            WHERE archived_at IS NULL
            ORDER BY created_at DESC, job_id DESC
            LIMIT 10
            """,
            (),
        ),
        (
            "build_jobs_status_list_idx",
            """
            SELECT job_id
            FROM graph_rag_control_plane.build_jobs
            WHERE archived_at IS NULL AND status = %s
            ORDER BY created_at DESC, job_id DESC
            LIMIT 10
            """,
            ("failed",),
        ),
        (
            "build_jobs_claim_idx",
            """
            SELECT job_id
            FROM graph_rag_control_plane.build_jobs
            WHERE archived_at IS NULL AND status = 'queued'
            ORDER BY created_at, job_id
            LIMIT 1
            """,
            (),
        ),
        (
            "build_jobs_lease_expiry_idx",
            """
            SELECT job_id
            FROM graph_rag_control_plane.build_jobs
            WHERE archived_at IS NULL
              AND status IN ('claimed', 'running', 'cancel_requested')
              AND lease_expires_at <= now()
            ORDER BY lease_expires_at, job_id
            LIMIT 100
            """,
            (),
        ),
        (
            "build_jobs_terminal_retention_idx",
            """
            SELECT job_id
            FROM graph_rag_control_plane.build_jobs
            WHERE archived_at IS NULL
              AND status IN ('succeeded', 'failed', 'cancelled', 'interrupted')
            ORDER BY finished_at DESC, job_id DESC
            LIMIT 100
            """,
            (),
        ),
        (
            "build_jobs_archive_purge_idx",
            """
            SELECT job_id
            FROM graph_rag_control_plane.build_jobs
            WHERE archived_at IS NOT NULL AND archived_at <= now()
            ORDER BY archived_at, job_id
            LIMIT 100
            """,
            (),
        ),
        (
            "build_job_events_list_idx",
            """
            SELECT event_id
            FROM graph_rag_control_plane.build_job_events
            ORDER BY occurred_at DESC, event_id DESC
            LIMIT 100
            """,
            (),
        ),
    )

    with psycopg.connect(postgres_dsn) as connection:
        connection.execute("SET LOCAL enable_seqscan = off")
        for expected_index, query, parameters in cases:
            row = connection.execute(
                f"EXPLAIN (FORMAT JSON) {query}",
                parameters,
            ).fetchone()
            assert row is not None
            assert expected_index in _plan_index_names(row[0]), (
                expected_index,
                row[0],
            )

"""Versioned PostgreSQL schema management for the build-job control plane."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from importlib import resources

import psycopg

from rag_modules.contracts.build_jobs import (
    BuildJobRepositoryError,
    BuildJobRepositoryUnavailableError,
)

_POSTGRESQL_MINIMUM_SERVER_VERSION = 160000
_ADVISORY_LOCK = (424902026, 1)
_MIGRATION_FILE_PATTERN = re.compile(r"(?P<version>[0-9]{4})_(?P<name>[a-z0-9_]+)\.sql\Z")
_LEDGER_EXISTS_SQL = "SELECT to_regclass('graph_rag_control_plane.schema_migrations') IS NOT NULL"
_READ_LEDGER_SQL = (
    "SELECT version, checksum FROM graph_rag_control_plane.schema_migrations ORDER BY version"
)
_CREATE_LEDGER_SQL = """
CREATE SCHEMA IF NOT EXISTS graph_rag_control_plane;
CREATE TABLE IF NOT EXISTS graph_rag_control_plane.schema_migrations (
    version integer PRIMARY KEY CHECK (version >= 1),
    name text NOT NULL,
    checksum text NOT NULL CHECK (checksum ~ '^[0-9a-f]{64}$'),
    applied_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""
_INSERT_LEDGER_SQL = """
INSERT INTO graph_rag_control_plane.schema_migrations (version, name, checksum)
VALUES (%s, %s, %s)
"""
_LOCK_SQL = "SELECT pg_advisory_lock(%s, %s)"
_UNLOCK_SQL = "SELECT pg_advisory_unlock(%s, %s)"


@dataclass(frozen=True, slots=True)
class BuildJobPostgresSchemaStatus:
    current_version: int
    required_version: int
    pending_versions: tuple[int, ...]
    ready: bool


@dataclass(frozen=True, slots=True)
class _Migration:
    version: int
    name: str
    sql: str
    checksum: str


def _discover_migrations() -> tuple[_Migration, ...]:
    try:
        return _discover_migrations_unchecked()
    except BuildJobRepositoryError:
        raise
    except Exception:
        raise BuildJobRepositoryError(
            "Build job PostgreSQL migration resources are unavailable."
        ) from None


def _discover_migrations_unchecked() -> tuple[_Migration, ...]:
    migration_root = resources.files(__package__).joinpath("migrations")
    discovered: list[_Migration] = []
    for resource in migration_root.iterdir():
        if not resource.is_file():
            continue
        match = _MIGRATION_FILE_PATTERN.fullmatch(resource.name)
        if match is None:
            if resource.name.endswith(".sql"):
                raise BuildJobRepositoryError(
                    "Build job PostgreSQL migration resources are invalid."
                )
            continue
        payload = resource.read_bytes()
        try:
            sql = payload.decode("utf-8")
        except UnicodeDecodeError:
            raise BuildJobRepositoryError(
                "Build job PostgreSQL migration resources are invalid."
            ) from None
        discovered.append(
            _Migration(
                version=int(match.group("version")),
                name=match.group("name"),
                sql=sql,
                checksum=hashlib.sha256(payload).hexdigest(),
            )
        )

    migrations = tuple(sorted(discovered, key=lambda migration: migration.version))
    versions = tuple(migration.version for migration in migrations)
    if not migrations or versions != tuple(range(1, len(migrations) + 1)):
        raise BuildJobRepositoryError("Build job PostgreSQL migration resources are invalid.")
    return migrations


class PostgresBuildJobSchemaManager:
    """Inspect, verify, and explicitly migrate the PostgreSQL build-job schema."""

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
        self._migrations = _discover_migrations()

    def status(self) -> BuildJobPostgresSchemaStatus:
        try:
            with psycopg.connect(self._dsn, autocommit=True) as connection:
                self._ensure_supported_server(connection)
                applied = self._read_applied_migrations(connection)
        except BuildJobRepositoryError:
            raise
        except Exception:
            raise BuildJobRepositoryUnavailableError(
                "Build job PostgreSQL schema status is unavailable."
            ) from None
        return self._build_status(applied)

    def verify(self) -> BuildJobPostgresSchemaStatus:
        try:
            status = self.status()
        except BuildJobRepositoryError:
            raise BuildJobRepositoryError("Build job PostgreSQL schema is not ready.") from None
        if not status.ready:
            raise BuildJobRepositoryError("Build job PostgreSQL schema is not ready.")
        return status

    def migrate(self) -> BuildJobPostgresSchemaStatus:
        connection = None
        locked = False
        try:
            connection = psycopg.connect(self._dsn, autocommit=True)
            self._ensure_supported_server(connection)
            connection.execute(_LOCK_SQL, _ADVISORY_LOCK)
            locked = True
            with connection.transaction():
                connection.execute(_CREATE_LEDGER_SQL)
            applied = self._read_applied_migrations(connection)
            self._validate_applied_migrations(applied)
            for migration in self._migrations:
                if migration.version in applied:
                    continue
                with connection.transaction():
                    connection.execute(migration.sql)
                    connection.execute(
                        _INSERT_LEDGER_SQL,
                        (migration.version, migration.name, migration.checksum),
                    )
                applied[migration.version] = migration.checksum
            status = self._build_status(applied)
            if not status.ready:
                raise BuildJobRepositoryError("Build job PostgreSQL schema is not ready.")
            return status
        except BuildJobRepositoryError:
            raise
        except Exception:
            raise BuildJobRepositoryError("Build job PostgreSQL schema migration failed.") from None
        finally:
            if connection is not None:
                if locked:
                    try:
                        connection.execute(_UNLOCK_SQL, _ADVISORY_LOCK)
                    except Exception:
                        pass
                try:
                    connection.close()
                except Exception:
                    pass

    @staticmethod
    def _ensure_supported_server(connection: psycopg.Connection[tuple[object, ...]]) -> None:
        if connection.info.server_version < _POSTGRESQL_MINIMUM_SERVER_VERSION:
            raise BuildJobRepositoryError("Build job PostgreSQL server version is unsupported.")

    @staticmethod
    def _read_applied_migrations(
        connection: psycopg.Connection[tuple[object, ...]],
    ) -> dict[int, str]:
        relation_row = connection.execute(_LEDGER_EXISTS_SQL).fetchone()
        if relation_row is None or not bool(relation_row[0]):
            return {}
        applied: dict[int, str] = {}
        for version, checksum in connection.execute(_READ_LEDGER_SQL).fetchall():
            if (
                isinstance(version, bool)
                or not isinstance(version, int)
                or not isinstance(checksum, str)
            ):
                raise BuildJobRepositoryError("Build job PostgreSQL migration history is invalid.")
            applied[version] = checksum
        return applied

    def _validate_applied_migrations(self, applied: dict[int, str]) -> None:
        expected = {migration.version: migration.checksum for migration in self._migrations}
        if any(expected.get(version) != checksum for version, checksum in applied.items()):
            raise BuildJobRepositoryError("Build job PostgreSQL migration history is invalid.")

    def _build_status(self, applied: dict[int, str]) -> BuildJobPostgresSchemaStatus:
        expected = {migration.version: migration.checksum for migration in self._migrations}
        pending = tuple(version for version in expected if version not in applied)
        return BuildJobPostgresSchemaStatus(
            current_version=max(applied, default=0),
            required_version=self._migrations[-1].version,
            pending_versions=pending,
            ready=applied == expected,
        )

from __future__ import annotations

import os
from collections.abc import Iterator

import psycopg
import pytest

TEST_POSTGRES_DSN_ENV = "BUILD_JOB_TEST_POSTGRES_DSN"
TEST_POSTGRES_RESET_ENV = "BUILD_JOB_TEST_ALLOW_RESET"
CONTROL_PLANE_SCHEMA = "graph_rag_control_plane"


def guarded_postgres_dsn() -> str:
    dsn = os.environ.get(TEST_POSTGRES_DSN_ENV, "").strip()
    reset_allowed = os.environ.get(TEST_POSTGRES_RESET_ENV) == "1"
    if not dsn or not reset_allowed:
        pytest.skip(
            "PostgreSQL schema integration tests require BUILD_JOB_TEST_POSTGRES_DSN "
            "and BUILD_JOB_TEST_ALLOW_RESET=1."
        )
    return dsn


def reset_control_plane_schema(dsn: str) -> None:
    if (
        dsn != os.environ.get(TEST_POSTGRES_DSN_ENV, "").strip()
        or os.environ.get(TEST_POSTGRES_RESET_ENV) != "1"
    ):
        raise RuntimeError("PostgreSQL test schema reset guard is not enabled.")
    with psycopg.connect(dsn, autocommit=True) as connection:
        connection.execute(f"DROP SCHEMA IF EXISTS {CONTROL_PLANE_SCHEMA} CASCADE")


@pytest.fixture
def postgres_dsn() -> Iterator[str]:
    dsn = guarded_postgres_dsn()
    reset_control_plane_schema(dsn)
    try:
        yield dsn
    finally:
        reset_control_plane_schema(dsn)

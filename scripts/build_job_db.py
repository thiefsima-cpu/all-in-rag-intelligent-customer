"""Explicit PostgreSQL schema management for the build-job control plane."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence

from rag_modules.configuration import load_config
from rag_modules.runtime.build_jobs.postgres import (
    BuildJobPostgresSchemaStatus,
    PostgresBuildJobSchemaManager,
)

_SAFE_ERROR = "Build job PostgreSQL schema operation failed."


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("status", "migrate"):
        subparser = subparsers.add_parser(command)
        subparser.add_argument("--json", action="store_true")
    return parser


def _status_payload(status: BuildJobPostgresSchemaStatus) -> dict[str, object]:
    return {
        "current_version": status.current_version,
        "required_version": status.required_version,
        "pending_versions": status.pending_versions,
        "ready": status.ready,
    }


def _print_status(status: BuildJobPostgresSchemaStatus, *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(_status_payload(status), sort_keys=True))
        return
    pending = ",".join(str(version) for version in status.pending_versions) or "none"
    print(
        "build job PostgreSQL schema: "
        f"current_version={status.current_version} "
        f"required_version={status.required_version} "
        f"pending_versions={pending} "
        f"ready={status.ready}"
    )


def _print_error(*, as_json: bool) -> None:
    if as_json:
        print(json.dumps({"error": _SAFE_ERROR, "ready": False}, sort_keys=True))
        return
    print(_SAFE_ERROR)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        dsn = load_config().storage.build_job_postgres_dsn
        manager = PostgresBuildJobSchemaManager(dsn)
        status = manager.status() if args.command == "status" else manager.migrate()
    except Exception:
        _print_error(as_json=args.json)
        return 1

    _print_status(status, as_json=args.json)
    return 0 if status.ready else 1


if __name__ == "__main__":
    raise SystemExit(main())

"""Explicit PostgreSQL schema management for the build-job control plane."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from rag_modules.configuration import load_config
from rag_modules.runtime.build_jobs.postgres import (
    BuildJobImportReport,
    BuildJobPostgresSchemaStatus,
    PostgresBuildJobRepository,
    PostgresBuildJobSchemaManager,
    V3BuildJobImporter,
)

_SAFE_ERROR = "Build job PostgreSQL schema operation failed."
_SAFE_IMPORT_ERROR = "Build job PostgreSQL file import failed."


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("status", "migrate"):
        subparser = subparsers.add_parser(command)
        subparser.add_argument("--json", action="store_true")
    import_parser = subparsers.add_parser("import-file")
    import_parser.add_argument("--source", type=Path, required=True)
    import_parser.add_argument("--dry-run", action="store_true")
    import_parser.add_argument("--json", action="store_true")
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


def _print_import_report(report: BuildJobImportReport, *, as_json: bool) -> None:
    payload = asdict(report)
    if as_json:
        print(json.dumps(payload, sort_keys=True))
        return
    print(
        "build job PostgreSQL file import: "
        f"scanned_jobs={report.scanned_jobs} "
        f"scanned_events={report.scanned_events} "
        f"imported_jobs={report.imported_jobs} "
        f"skipped_jobs={report.skipped_jobs} "
        f"conflicts={report.conflicts} "
        f"dry_run={report.dry_run}"
    )


def _print_import_error(*, as_json: bool) -> None:
    if as_json:
        print(json.dumps({"error": _SAFE_IMPORT_ERROR, "ready": False}, sort_keys=True))
        return
    print(_SAFE_IMPORT_ERROR)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _import_file(args: argparse.Namespace) -> int:
    repository: PostgresBuildJobRepository | None = None
    try:
        config = load_config()
        repository = PostgresBuildJobRepository(
            config.storage.build_job_postgres_dsn,
            now=_utc_now,
            pool_min_size=config.api.build_job_postgres_pool_min_size,
            pool_max_size=config.api.build_job_postgres_pool_max_size,
            pool_timeout_seconds=config.api.build_job_postgres_pool_timeout_seconds,
        )
        report = V3BuildJobImporter(repository).run(args.source, dry_run=args.dry_run)
    except Exception:
        _print_import_error(as_json=args.json)
        return 1
    finally:
        if repository is not None:
            try:
                repository.close()
            except Exception:
                pass
    _print_import_report(report, as_json=args.json)
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "import-file":
        return _import_file(args)
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

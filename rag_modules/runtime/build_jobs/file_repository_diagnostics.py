"""Diagnostics scans for file-backed build-job repositories."""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

from rag_modules.contracts.build_jobs import BuildJobId

from . import file_repository_idempotency as idempotency
from . import file_repository_storage as storage

if TYPE_CHECKING:
    from .file_repository import FileBuildJobRepository


def scan_for_corruption(repository: FileBuildJobRepository) -> None:
    if not os.path.isdir(repository.jobs_dir):
        idempotency.scan_idempotency_for_corruption(repository)
        return
    for path in Path(repository.jobs_dir).glob("*.json"):
        try:
            job_id = BuildJobId(path.stem)
        except ValueError:
            storage.record_warning(repository, "BUILD_JOB_STORE_CORRUPT_RECORD", "job", path.stem)
            continue
        storage.load_envelope(repository, job_id)
    idempotency.scan_idempotency_for_corruption(repository)


__all__ = ["scan_for_corruption"]

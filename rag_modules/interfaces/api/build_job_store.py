"""Compatibility facade for persistent asynchronous build-job state."""

from __future__ import annotations

from .build_jobs import (
    BUILD_JOB_LOG_LIMIT,
    BUILD_JOB_STORE_SCHEMA_VERSION,
    BuildJobCorruptionWarning,
    BuildJobIdempotencyConflictError,
    BuildJobListPage,
    BuildJobRecord,
    BuildJobRepository,
    BuildJobRepositorySettings,
    FileBuildJobStore,
    PersistentBuildJobRegistry,
    default_build_job_store_path,
)

__all__ = [
    "BUILD_JOB_LOG_LIMIT",
    "BUILD_JOB_STORE_SCHEMA_VERSION",
    "BuildJobCorruptionWarning",
    "BuildJobIdempotencyConflictError",
    "BuildJobListPage",
    "BuildJobRecord",
    "BuildJobRepository",
    "BuildJobRepositorySettings",
    "FileBuildJobStore",
    "PersistentBuildJobRegistry",
    "default_build_job_store_path",
]

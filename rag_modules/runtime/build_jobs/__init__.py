"""Concrete build-job runtime adapters."""

from __future__ import annotations

from .external_worker_runner import ExternalBuildJobQueueRunner, ExternalBuildJobWorkerRunner
from .file_repository import (
    FileBuildJobRepository,
    hash_idempotency_key,
    new_queued_event,
    validate_idempotency_key,
)
from .in_process_runner import BuildLeaseRecorder, InProcessBuildJobRunner
from .migration import BuildJobStoreMigrator
from .postgres import PostgresBuildJobRepository
from .serialization import (
    BUILD_JOB_ENVELOPE_SCHEMA_VERSION,
    BuildJobEnvelope,
    envelope_from_dict,
    envelope_to_dict,
    snapshot_from_dict,
    snapshot_to_dict,
)

__all__ = [
    "BUILD_JOB_ENVELOPE_SCHEMA_VERSION",
    "BuildJobEnvelope",
    "BuildJobStoreMigrator",
    "BuildLeaseRecorder",
    "ExternalBuildJobQueueRunner",
    "ExternalBuildJobWorkerRunner",
    "FileBuildJobRepository",
    "InProcessBuildJobRunner",
    "PostgresBuildJobRepository",
    "envelope_from_dict",
    "envelope_to_dict",
    "hash_idempotency_key",
    "new_queued_event",
    "snapshot_from_dict",
    "snapshot_to_dict",
    "validate_idempotency_key",
]

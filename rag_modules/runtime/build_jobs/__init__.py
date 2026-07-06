"""Concrete build-job runtime adapters."""

from __future__ import annotations

from .file_repository import (
    FileBuildJobRepository,
    hash_idempotency_key,
    new_queued_event,
    validate_idempotency_key,
)
from .migration import BuildJobStoreMigrator
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
    "FileBuildJobRepository",
    "envelope_from_dict",
    "envelope_to_dict",
    "hash_idempotency_key",
    "new_queued_event",
    "snapshot_from_dict",
    "snapshot_to_dict",
    "validate_idempotency_key",
]

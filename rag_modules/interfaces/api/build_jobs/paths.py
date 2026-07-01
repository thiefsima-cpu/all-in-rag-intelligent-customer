"""Build-job store path resolution."""

from __future__ import annotations

import os
from typing import Any


def default_build_job_store_path(config: Any) -> str:
    storage = getattr(config, "storage", None)
    configured_path = str(getattr(storage, "build_job_store_path", "") or "")
    if configured_path:
        return configured_path
    manifest_path = str(
        getattr(storage, "artifact_manifest_path", "")
        or os.path.join("storage", "indexes", "artifact_manifest.json")
    )
    return os.path.join(os.path.dirname(manifest_path), "build_jobs.json")


__all__ = ["default_build_job_store_path"]

from __future__ import annotations

import tempfile
from collections.abc import Mapping
from pathlib import Path
from uuid import uuid4

from rag_modules.configuration.env import EnvConfigSource
from rag_modules.configuration.loader import load_config
from rag_modules.configuration.models import GraphRAGConfig
from rag_modules.kernel.json_types import JsonObject, coerce_json_object

_EMPTY_ENV_SOURCE = EnvConfigSource(environ={})


def build_test_config(overrides: Mapping[str, object] | None = None) -> GraphRAGConfig:
    store = Path(tempfile.gettempdir()) / f"graph-rag-c9-build-jobs-{uuid4().hex}" / "jobs.json"
    payload: JsonObject = {
        "api": {"build_job_repository_backend": "file"},
        "storage": {"build_job_store_path": str(store)},
    }
    for section, values in coerce_json_object(overrides).items():
        existing_values = payload.get(section)
        if isinstance(values, dict) and isinstance(existing_values, dict):
            existing_values.update(values)
        else:
            payload[section] = values
    api_payload = payload.get("api")
    if isinstance(api_payload, dict):
        api_payload["build_job_repository_backend"] = "file"
    return load_config(overrides=payload, source=_EMPTY_ENV_SOURCE)


__all__ = ["build_test_config"]

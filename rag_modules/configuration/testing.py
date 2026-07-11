"""Deterministic config helpers for tests and offline smoke suites."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any, Mapping
from uuid import uuid4

from ..contracts import QueryPlannerRuntimeSettings, QuerySemanticRuntimeSettings
from .env import EnvConfigSource
from .loader import load_config
from .models import GraphRAGConfig

_EMPTY_ENV_SOURCE = EnvConfigSource(environ={})


def _merge_nested_mapping(target: dict[str, Any], updates: Mapping[str, Any]) -> None:
    for key, value in updates.items():
        key_text = str(key)
        current = target.get(key_text)
        if isinstance(current, dict) and isinstance(value, Mapping):
            _merge_nested_mapping(current, value)
        else:
            target[key_text] = dict(value) if isinstance(value, Mapping) else value


def _temporary_build_job_store_path() -> str:
    store_dir = Path(tempfile.gettempdir()) / f"graph-rag-c9-build-jobs-{uuid4().hex}"
    return str(store_dir / "build_jobs.json")


def _test_overrides(overrides: Mapping[str, Any] | None) -> dict[str, Any]:
    resolved: dict[str, Any] = {
        "storage": {"build_job_store_path": _temporary_build_job_store_path()}
    }
    if overrides:
        _merge_nested_mapping(resolved, overrides)
    return resolved


def build_test_config(overrides: Mapping[str, Any] | None = None) -> GraphRAGConfig:
    """Build a deterministic config from loader defaults plus explicit overrides."""

    return load_config(overrides=_test_overrides(overrides), source=_EMPTY_ENV_SOURCE)


def planner_runtime_settings(config: GraphRAGConfig) -> QueryPlannerRuntimeSettings:
    return QueryPlannerRuntimeSettings.from_config(config)


def semantic_runtime_settings(config: GraphRAGConfig) -> QuerySemanticRuntimeSettings:
    return QuerySemanticRuntimeSettings.from_config(config)


__all__ = ["build_test_config", "planner_runtime_settings", "semantic_runtime_settings"]

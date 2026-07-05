"""Deterministic config helpers for tests and offline smoke suites."""

from __future__ import annotations

from typing import Any, Mapping

from ..contracts import QueryPlannerRuntimeSettings, QuerySemanticRuntimeSettings
from .env import EnvConfigSource
from .loader import load_config
from .models import GraphRAGConfig

_EMPTY_ENV_SOURCE = EnvConfigSource(environ={})


def build_test_config(overrides: Mapping[str, Any] | None = None) -> GraphRAGConfig:
    """Build a deterministic config from loader defaults plus explicit overrides."""

    return load_config(overrides=overrides or {}, source=_EMPTY_ENV_SOURCE)


def planner_runtime_settings(config: GraphRAGConfig) -> QueryPlannerRuntimeSettings:
    return QueryPlannerRuntimeSettings.from_config(config)


def semantic_runtime_settings(config: GraphRAGConfig) -> QuerySemanticRuntimeSettings:
    return QuerySemanticRuntimeSettings.from_config(config)


__all__ = ["build_test_config", "planner_runtime_settings", "semantic_runtime_settings"]

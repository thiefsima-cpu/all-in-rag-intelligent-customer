"""Deterministic config helpers for tests and offline smoke suites."""

from __future__ import annotations

from typing import Any, Mapping

from .env import EnvConfigSource
from .loader import load_config
from .models import GraphRAGConfig

_EMPTY_ENV_SOURCE = EnvConfigSource(environ={})


def build_test_config(overrides: Mapping[str, Any] | None = None) -> GraphRAGConfig:
    """Build a deterministic config from loader defaults plus explicit overrides."""

    return load_config(overrides=overrides or {}, source=_EMPTY_ENV_SOURCE)


__all__ = ["build_test_config"]

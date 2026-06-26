"""Observability configuration section loader."""

from __future__ import annotations

from typing import Any, Mapping

from ..env import EnvConfigSource
from ..models import ObservabilitySettings
from .common import load_section_from_schema


def load_observability_settings(
    source: EnvConfigSource,
    defaults: Mapping[str, Any] | None = None,
) -> ObservabilitySettings:
    return load_section_from_schema("observability", source, defaults)


__all__ = ["load_observability_settings"]

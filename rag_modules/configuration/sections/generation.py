"""Generation configuration section loader."""

from __future__ import annotations

from typing import Any, Mapping

from ..env import EnvConfigSource
from ..models import GenerationSettings
from .common import load_section_from_schema


def load_generation_settings(
    source: EnvConfigSource,
    defaults: Mapping[str, Any] | None = None,
) -> GenerationSettings:
    return load_section_from_schema("generation", source, defaults)


__all__ = ["load_generation_settings"]

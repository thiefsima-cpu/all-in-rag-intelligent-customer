"""Model provider configuration section loader."""

from __future__ import annotations

from typing import Any, Mapping

from ..env import EnvConfigSource
from ..models import ModelSettings
from .common import load_section_from_schema


def load_model_settings(
    source: EnvConfigSource,
    defaults: Mapping[str, Any] | None = None,
) -> ModelSettings:
    return load_section_from_schema("models", source, defaults)


__all__ = ["load_model_settings"]

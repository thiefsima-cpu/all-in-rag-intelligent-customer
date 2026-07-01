"""API configuration section loader."""

from __future__ import annotations

from typing import Any, Mapping

from ..env import EnvConfigSource
from ..models import ApiSettings
from .common import load_section_from_schema


def load_api_settings(
    source: EnvConfigSource,
    defaults: Mapping[str, Any] | None = None,
) -> ApiSettings:
    return load_section_from_schema("api", source, defaults)


__all__ = ["load_api_settings"]

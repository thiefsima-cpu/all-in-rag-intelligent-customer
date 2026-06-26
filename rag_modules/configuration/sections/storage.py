"""Storage configuration section loader."""

from __future__ import annotations

from typing import Any, Mapping

from ..env import EnvConfigSource
from ..models import StorageSettings
from .common import load_section_from_schema


def load_storage_settings(
    source: EnvConfigSource,
    defaults: Mapping[str, Any] | None = None,
) -> StorageSettings:
    return load_section_from_schema("storage", source, defaults)


__all__ = ["load_storage_settings"]

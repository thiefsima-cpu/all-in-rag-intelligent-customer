"""Retrieval configuration section loader."""

from __future__ import annotations

from typing import Any, Mapping

from ..env import EnvConfigSource
from ..models import RetrievalSettings
from .common import load_section_from_schema


def load_retrieval_settings(
    source: EnvConfigSource,
    defaults: Mapping[str, Any] | None = None,
) -> RetrievalSettings:
    return load_section_from_schema("retrieval", source, defaults)


__all__ = ["load_retrieval_settings"]

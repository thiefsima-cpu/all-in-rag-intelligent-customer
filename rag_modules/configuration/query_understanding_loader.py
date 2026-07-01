"""Dedicated loader for query-understanding configuration sections."""

from __future__ import annotations

from typing import Any, Mapping

from .env import EnvConfigSource
from .models import QueryUnderstandingSettings
from .sections.common import load_section_from_schema


def load_query_understanding_settings(
    source: EnvConfigSource,
    defaults: Mapping[str, Any] | None = None,
) -> QueryUnderstandingSettings:
    return load_section_from_schema("query_understanding", source, defaults)


__all__ = ["load_query_understanding_settings"]

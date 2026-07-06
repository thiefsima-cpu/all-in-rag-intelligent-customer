"""Graph construction and ranking configuration section loader."""

from __future__ import annotations

from typing import Any, Mapping

from ..env import EnvConfigSource
from ..models import GraphSettings
from .common import load_section_from_schema


def load_graph_settings(
    source: EnvConfigSource,
    defaults: Mapping[str, Any] | None = None,
) -> GraphSettings:
    return load_section_from_schema("graph", source, defaults)


__all__ = ["load_graph_settings"]

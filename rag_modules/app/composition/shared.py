"""Shared helpers for runtime composition."""

from __future__ import annotations

from typing import Callable, Optional

from ...configuration import get_default_config
from ...configuration.models import GraphRAGConfig

ProgressCallback = Optional[Callable[[str], None]]


def resolve_config(config: GraphRAGConfig | None) -> GraphRAGConfig:
    return config or get_default_config()


def emit_progress(progress: ProgressCallback, message: str) -> None:
    if progress:
        progress(message)

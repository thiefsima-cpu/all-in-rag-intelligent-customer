"""Shared helpers for runtime composition."""

from __future__ import annotations

from typing import Any, Callable, Optional

from ...configuration import get_default_config
from ...configuration.models import GraphRAGConfig

ProgressCallback = Optional[Callable[[str], None]]


def resolve_config(config: GraphRAGConfig | None) -> GraphRAGConfig:
    return config or get_default_config()


def emit_progress(progress: ProgressCallback, message: str) -> None:
    if progress:
        progress(message)


def provide_routing_workflow_compat(provider: Any, **kwargs: Any) -> Any:
    workflow_provider = getattr(provider, "provide_routing_workflow", None)
    if callable(workflow_provider):
        return workflow_provider(**kwargs)
    return provider.provide_query_router(**kwargs)

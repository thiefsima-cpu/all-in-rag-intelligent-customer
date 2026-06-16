"""Helpers for cloning and normalizing runtime trace snapshots."""

from __future__ import annotations

from typing import Any

from .generation_models import GenerationSnapshot
from .graph_models import GraphRetrievalSnapshot
from .route_models import RouteSnapshot


def clone_route_snapshot(value: Any = None) -> RouteSnapshot:
    if isinstance(value, RouteSnapshot):
        return RouteSnapshot.from_dict(value.to_dict())
    return RouteSnapshot.from_dict(value or {})


def clone_graph_snapshot(value: Any = None) -> GraphRetrievalSnapshot:
    if isinstance(value, GraphRetrievalSnapshot):
        return GraphRetrievalSnapshot.from_dict(value.to_dict())
    return GraphRetrievalSnapshot.from_dict(value or {})


def clone_generation_snapshot(value: Any = None) -> GenerationSnapshot:
    if isinstance(value, GenerationSnapshot):
        return GenerationSnapshot.from_dict(value.to_dict())
    return GenerationSnapshot.from_dict(value or {})


__all__ = [
    "clone_generation_snapshot",
    "clone_graph_snapshot",
    "clone_route_snapshot",
]

"""Helpers for cloning and normalizing runtime trace snapshots."""

from __future__ import annotations

from typing import Any

from ..contracts import QuerySemanticRuntimeSettings
from ..contracts.runtime import GenerationSnapshot, GraphRetrievalSnapshot, RouteSnapshot


def clone_route_snapshot(
    value: Any = None,
    *,
    semantic_settings: QuerySemanticRuntimeSettings,
) -> RouteSnapshot:
    if isinstance(value, RouteSnapshot):
        return RouteSnapshot.from_dict(
            value.to_dict(),
            semantic_settings=semantic_settings,
        )
    return RouteSnapshot.from_dict(value or {}, semantic_settings=semantic_settings)


def clone_graph_snapshot(
    value: Any = None,
    *,
    semantic_settings: QuerySemanticRuntimeSettings,
) -> GraphRetrievalSnapshot:
    if isinstance(value, GraphRetrievalSnapshot):
        return GraphRetrievalSnapshot.from_dict(
            value.to_dict(),
            semantic_settings=semantic_settings,
        )
    return GraphRetrievalSnapshot.from_dict(value or {}, semantic_settings=semantic_settings)


def clone_generation_snapshot(value: Any = None) -> GenerationSnapshot:
    if isinstance(value, GenerationSnapshot):
        return GenerationSnapshot.from_dict(value.to_dict())
    return GenerationSnapshot.from_dict(value or {})


__all__ = [
    "clone_generation_snapshot",
    "clone_graph_snapshot",
    "clone_route_snapshot",
]

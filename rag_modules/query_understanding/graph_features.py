"""Graph query feature inference."""

from __future__ import annotations

from typing import List

from .entity_features import pairwise_entity_matches
from .lexical_features import _active_registry
from .registry import (
    QueryUnderstandingRegistry,
    contains_any,
    dedupe_preserve_order,
    normalize_query_text,
)


def infer_graph_query_type(
    query: str,
    *,
    registry: QueryUnderstandingRegistry | None = None,
) -> str:
    active_registry = _active_registry(registry)
    normalized = normalize_query_text(query)
    if not normalized:
        return "entity_relation"
    if contains_any(normalized, active_registry.path_markers) or pairwise_entity_matches(
        normalized,
        registry=active_registry,
    ):
        return "path_finding"
    if contains_any(normalized, active_registry.subgraph_markers):
        return "subgraph"
    if contains_any(normalized, active_registry.clustering_markers):
        return "clustering"
    if contains_any(normalized, active_registry.relation_markers) or contains_any(
        normalized, active_registry.structural_reasoning_markers
    ):
        return "multi_hop"
    return "entity_relation"


def infer_relation_types(
    query: str,
    *,
    registry: QueryUnderstandingRegistry | None = None,
) -> List[str]:
    active_registry = _active_registry(registry)
    normalized = normalize_query_text(query)
    relation_types: List[str] = []
    for relation_type, markers in active_registry.relation_query_markers.items():
        if relation_type in active_registry.graph_relation_types and contains_any(
            normalized,
            markers,
        ):
            relation_types.append(relation_type)
    return dedupe_preserve_order(relation_types)


__all__ = [
    "infer_graph_query_type",
    "infer_relation_types",
]

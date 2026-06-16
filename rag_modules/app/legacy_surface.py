"""Data-driven compatibility mapping for legacy flat app/runtime attributes."""

from __future__ import annotations

from typing import Iterable, Mapping


GroupedLegacyAttributeMap = Mapping[str, tuple[str, str]]


GROUPED_LEGACY_ATTRIBUTE_MAP: dict[str, tuple[str, str]] = {
    "query_tracer": ("infrastructure", "query_tracer"),
    "neo4j_manager": ("infrastructure", "neo4j_manager"),
    "data_module": ("infrastructure", "data_module"),
    "index_module": ("infrastructure", "index_module"),
    "generation_module": ("services", "generation_service"),
    "generation_service": ("services", "generation_service"),
    "retrieval_runtime_profile": ("retrieval", "retrieval_runtime_profile"),
    "query_understanding_service": ("retrieval", "query_understanding_service"),
    "traditional_retrieval": ("retrieval", "traditional_retrieval"),
    "graph_rag_retrieval": ("retrieval", "graph_rag_retrieval"),
    "query_router": ("retrieval", "routing_workflow"),
    "routing_workflow": ("retrieval", "routing_workflow"),
    "knowledge_base_service": ("services", "knowledge_base_service"),
    "answer_workflow": ("services", "answer_workflow"),
    "question_answer_service": ("services", "question_answer_service"),
}


def resolve_grouped_legacy_attribute(
    owner: object,
    attribute_map: GroupedLegacyAttributeMap,
    name: str,
):
    target = attribute_map.get(name)
    if target is None:
        raise AttributeError(f"{type(owner).__name__!s} has no attribute {name!r}")
    group_name, attribute_name = target
    view = getattr(owner, group_name)
    return getattr(view, attribute_name)


def merge_legacy_dir_names(
    base_names: Iterable[str],
    attribute_map: GroupedLegacyAttributeMap,
) -> list[str]:
    return sorted(set(base_names) | set(attribute_map))


__all__ = [
    "GROUPED_LEGACY_ATTRIBUTE_MAP",
    "GroupedLegacyAttributeMap",
    "merge_legacy_dir_names",
    "resolve_grouped_legacy_attribute",
]

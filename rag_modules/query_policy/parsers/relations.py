"""Relation policy parser."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from ..models import GraphReasoningPolicy, PolicyLoadError, RelationPolicy
from .common import (
    optional_mapping,
    require_keys,
    required_mapping,
    to_str_map,
    to_tuple,
    to_tuple_map,
)

_REQUIRED_KEYS = ("preferred_relation_excluded_types", "relation_index_suffix_templates")


def parse_relations(
    policy_payload: Mapping[str, object],
    root: Path,
    *,
    graph_reasoning: GraphReasoningPolicy,
) -> RelationPolicy:
    payload = required_mapping(policy_payload, "relations", root)
    require_keys(payload, _REQUIRED_KEYS, root, "relations")
    entity_linker = optional_mapping(
        payload.get("entity_linker"),
        root,
        "relations.entity_linker",
    )

    relation_types = to_tuple(payload.get("graph_relation_types"))
    preferred_relation_excluded_types = to_tuple(payload.get("preferred_relation_excluded_types"))
    relation_index_keywords = to_tuple_map(
        payload.get("relation_index_keywords"),
        root,
        "relations.relation_index_keywords",
    )
    relation_index_suffix_templates = to_str_map(
        payload.get("relation_index_suffix_templates"),
        root,
        "relations.relation_index_suffix_templates",
    )
    relation_query_markers = to_tuple_map(
        payload.get("relation_query_markers"),
        root,
        "relations.relation_query_markers",
    )
    _verify_relation_references(
        relation_types,
        preferred_relation_excluded_types,
        relation_index_keywords,
        relation_index_suffix_templates,
        relation_query_markers,
        graph_reasoning,
        root,
    )

    return RelationPolicy(
        graph_routing_strategies=to_tuple(payload.get("graph_routing_strategies")),
        graph_query_types=to_tuple(payload.get("graph_query_types")),
        graph_relation_types=relation_types,
        preferred_relation_excluded_types=preferred_relation_excluded_types,
        semantic_relation_hints=to_str_map(
            payload.get("semantic_relation_hints"),
            root,
            "relations.semantic_relation_hints",
        ),
        relation_index_keywords=relation_index_keywords,
        relation_index_suffix_templates=relation_index_suffix_templates,
        relation_query_markers=relation_query_markers,
        entity_linker_preferred_labels=to_tuple(entity_linker.get("preferred_labels")),
        entity_linker_query_type_priorities=to_tuple_map(
            entity_linker.get("query_type_priorities"),
            root,
            "relations.entity_linker.query_type_priorities",
        ),
        entity_linker_relation_priorities=to_tuple_map(
            entity_linker.get("relation_priorities"),
            root,
            "relations.entity_linker.relation_priorities",
        ),
    )


def _verify_relation_references(
    relation_types: tuple[str, ...],
    preferred_relation_excluded_types: tuple[str, ...],
    relation_index_keywords: Mapping[str, tuple[str, ...]],
    relation_index_suffix_templates: Mapping[str, str],
    relation_query_markers: Mapping[str, tuple[str, ...]],
    graph_reasoning: GraphReasoningPolicy,
    root: Path,
) -> None:
    known = set(relation_types)
    for field_name, relation_map in (
        ("relations.preferred_relation_excluded_types", preferred_relation_excluded_types),
        ("relations.relation_index_keywords", relation_index_keywords),
        ("relations.relation_index_suffix_templates", relation_index_suffix_templates),
        ("relations.relation_query_markers", relation_query_markers),
        ("graph.reasoning.causal_relation_types", graph_reasoning.causal_relation_types),
        (
            "graph.reasoning.compositional_relation_types",
            graph_reasoning.compositional_relation_types,
        ),
        (
            "graph.reasoning.semantic_relation_key_specs",
            tuple(graph_reasoning.semantic_relation_key_specs),
        ),
    ):
        unknown = sorted(set(relation_map) - known)
        if unknown:
            raise PolicyLoadError(
                f"Unknown graph relation type: {unknown[0]}",
                bundle_path=str(root),
                field_path=f"{field_name}.{unknown[0]}",
            )

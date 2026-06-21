"""Graph configuration section loader."""

from __future__ import annotations

from typing import Any, Mapping

from ...query_understanding.registry import (
    default_entity_linker_query_type_priorities,
    default_entity_linker_relation_priorities,
)
from ..env import EnvConfigSource
from ..models import GraphSettings
from .common import mapping_defaults


def load_graph_settings(
    source: EnvConfigSource,
    defaults: Mapping[str, Any] | None = None,
) -> GraphSettings:
    graph_defaults = mapping_defaults(defaults)
    return GraphSettings(
        enable_semantic_graph_schema=source.get_bool(
            "ENABLE_SEMANTIC_GRAPH_SCHEMA",
            bool(graph_defaults.get("enable_semantic_graph_schema", True)),
        ),
        chunk_size=source.get_int("CHUNK_SIZE", int(graph_defaults.get("chunk_size", 500))),
        chunk_overlap=source.get_int(
            "CHUNK_OVERLAP",
            int(graph_defaults.get("chunk_overlap", 50)),
        ),
        max_graph_depth=source.get_int(
            "MAX_GRAPH_DEPTH",
            int(graph_defaults.get("max_graph_depth", 2)),
        ),
        graph_rank_base_weight=source.get_float(
            "GRAPH_RANK_BASE_WEIGHT",
            float(graph_defaults.get("graph_rank_base_weight", 1.0)),
        ),
        graph_rank_semantic_relation_weight=source.get_float(
            "GRAPH_RANK_SEMANTIC_RELATION_WEIGHT",
            float(graph_defaults.get("graph_rank_semantic_relation_weight", 0.08)),
        ),
        graph_rank_evidence_unit_weight=source.get_float(
            "GRAPH_RANK_EVIDENCE_UNIT_WEIGHT",
            float(graph_defaults.get("graph_rank_evidence_unit_weight", 0.03)),
        ),
        graph_rank_relationship_weight=source.get_float(
            "GRAPH_RANK_RELATIONSHIP_WEIGHT",
            float(graph_defaults.get("graph_rank_relationship_weight", 0.01)),
        ),
        graph_rank_recipe_presence_weight=source.get_float(
            "GRAPH_RANK_RECIPE_PRESENCE_WEIGHT",
            float(graph_defaults.get("graph_rank_recipe_presence_weight", 0.1)),
        ),
        graph_rank_query_overlap_weight=source.get_float(
            "GRAPH_RANK_QUERY_OVERLAP_WEIGHT",
            float(graph_defaults.get("graph_rank_query_overlap_weight", 0.02)),
        ),
        entity_linker_limit_per_entity=source.get_int(
            "ENTITY_LINKER_LIMIT_PER_ENTITY",
            int(graph_defaults.get("entity_linker_limit_per_entity", 4)),
        ),
        entity_linker_min_confidence=source.get_float(
            "ENTITY_LINKER_MIN_CONFIDENCE",
            float(graph_defaults.get("entity_linker_min_confidence", 0.45)),
        ),
        entity_linker_max_same_name_candidates=source.get_int(
            "ENTITY_LINKER_MAX_SAME_NAME_CANDIDATES",
            int(graph_defaults.get("entity_linker_max_same_name_candidates", 2)),
        ),
        entity_linker_query_type_label_priorities=source.get_json_dict(
            "ENTITY_LINKER_QUERY_TYPE_LABEL_PRIORITIES",
            dict(
                graph_defaults.get(
                    "entity_linker_query_type_label_priorities",
                    default_entity_linker_query_type_priorities(),
                )
            ),
        ),
        entity_linker_relation_label_priorities=source.get_json_dict(
            "ENTITY_LINKER_RELATION_LABEL_PRIORITIES",
            dict(
                graph_defaults.get(
                    "entity_linker_relation_label_priorities",
                    default_entity_linker_relation_priorities(),
                )
            ),
        ),
    )


__all__ = ["load_graph_settings"]

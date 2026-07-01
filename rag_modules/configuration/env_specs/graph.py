"""Graph environment override specs."""

from __future__ import annotations

from .base import EnvFieldSpec
from .base import spec as _spec

GRAPH_ENV_FIELD_SPECS: tuple[EnvFieldSpec, ...] = (
    _spec("ENABLE_SEMANTIC_GRAPH_SCHEMA", ("graph", "enable_semantic_graph_schema"), "bool"),
    _spec("CHUNK_SIZE", ("graph", "chunk_size"), "int"),
    _spec("CHUNK_OVERLAP", ("graph", "chunk_overlap"), "int"),
    _spec("MAX_GRAPH_DEPTH", ("graph", "max_graph_depth"), "int"),
    _spec("GRAPH_RANK_BASE_WEIGHT", ("graph", "graph_rank_base_weight"), "float"),
    _spec(
        "GRAPH_RANK_SEMANTIC_RELATION_WEIGHT",
        ("graph", "graph_rank_semantic_relation_weight"),
        "float",
    ),
    _spec(
        "GRAPH_RANK_EVIDENCE_UNIT_WEIGHT",
        ("graph", "graph_rank_evidence_unit_weight"),
        "float",
    ),
    _spec("GRAPH_RANK_RELATIONSHIP_WEIGHT", ("graph", "graph_rank_relationship_weight"), "float"),
    _spec(
        "GRAPH_RANK_RECIPE_PRESENCE_WEIGHT",
        ("graph", "graph_rank_recipe_presence_weight"),
        "float",
    ),
    _spec("GRAPH_RANK_QUERY_OVERLAP_WEIGHT", ("graph", "graph_rank_query_overlap_weight"), "float"),
    _spec("ENTITY_LINKER_LIMIT_PER_ENTITY", ("graph", "entity_linker_limit_per_entity"), "int"),
    _spec("ENTITY_LINKER_MIN_CONFIDENCE", ("graph", "entity_linker_min_confidence"), "float"),
    _spec(
        "ENTITY_LINKER_MAX_SAME_NAME_CANDIDATES",
        ("graph", "entity_linker_max_same_name_candidates"),
        "int",
    ),
    _spec(
        "ENTITY_LINKER_QUERY_TYPE_LABEL_PRIORITIES",
        ("graph", "entity_linker_query_type_label_priorities"),
        "json_dict",
    ),
    _spec(
        "ENTITY_LINKER_RELATION_LABEL_PRIORITIES",
        ("graph", "entity_linker_relation_label_priorities"),
        "json_dict",
    ),
)


__all__ = ["GRAPH_ENV_FIELD_SPECS"]

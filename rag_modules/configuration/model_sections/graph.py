"""Graph configuration section model."""

from __future__ import annotations

from typing import Dict, List

from pydantic import Field

from rag_modules.query_understanding.registry import (
    default_entity_linker_query_type_priorities,
    default_entity_linker_relation_priorities,
)

from .base import ConfigSection


class GraphSettings(ConfigSection):
    enable_semantic_graph_schema: bool = True
    chunk_size: int = 500
    chunk_overlap: int = 50
    max_graph_depth: int = 2
    graph_rank_base_weight: float = 1.0
    graph_rank_semantic_relation_weight: float = 0.08
    graph_rank_evidence_unit_weight: float = 0.03
    graph_rank_relationship_weight: float = 0.01
    graph_rank_recipe_presence_weight: float = 0.1
    graph_rank_query_overlap_weight: float = 0.02
    entity_linker_limit_per_entity: int = 4
    entity_linker_min_confidence: float = 0.45
    entity_linker_max_same_name_candidates: int = 2
    entity_linker_query_type_label_priorities: Dict[str, List[str]] = Field(
        default_factory=default_entity_linker_query_type_priorities
    )
    entity_linker_relation_label_priorities: Dict[str, List[str]] = Field(
        default_factory=default_entity_linker_relation_priorities
    )


__all__ = ["GraphSettings"]

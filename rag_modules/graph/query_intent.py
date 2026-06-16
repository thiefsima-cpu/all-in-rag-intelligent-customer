"""
Heuristic graph query intent extraction.

This module now delegates shared lexical rules to ``query_semantics`` so the
graph route, query planner, and evaluation helpers all reason over the same
signals.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

from ..retrieval.runtime_profile import QuerySemanticRuntimeSettings
from ..query_understanding import (
    infer_graph_max_depth,
    infer_query_semantic_profile,
)


@dataclass
class GraphQueryIntent:
    query_type: str = "multi_hop"
    source_entities: List[str] = field(default_factory=list)
    target_entities: List[str] = field(default_factory=list)
    relation_types: List[str] = field(default_factory=list)
    max_depth: int = 2
    constraints: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "query_type": self.query_type,
            "source_entities": self.source_entities,
            "target_entities": self.target_entities,
            "relation_types": self.relation_types,
            "max_depth": self.max_depth,
            "constraints": self.constraints,
        }


def infer_graph_query_intent(
    query: str,
    *,
    semantic_settings: QuerySemanticRuntimeSettings | None = None,
) -> GraphQueryIntent:
    profile = infer_query_semantic_profile(query, settings=semantic_settings)
    return GraphQueryIntent(
        query_type=profile.query_type,
        source_entities=profile.source_entities,
        target_entities=profile.target_entities,
        relation_types=profile.relation_types,
        max_depth=infer_graph_max_depth(
            profile.query_type,
            profile.relationship_intensity,
            settings=semantic_settings,
        ),
        constraints=profile.constraints,
    )




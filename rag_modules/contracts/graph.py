"""Graph retrieval request contracts."""

from __future__ import annotations

from dataclasses import dataclass, field

from ..kernel.json_types import JsonObject
from .query_types import GraphQueryType

QueryType = GraphQueryType


@dataclass
class GraphQuery:
    query_type: QueryType
    source_entities: list[str] = field(default_factory=list)
    target_entities: list[str] = field(default_factory=list)
    relation_types: list[str] = field(default_factory=list)
    max_depth: int = 2
    max_nodes: int = 50
    constraints: JsonObject = field(default_factory=dict)


__all__ = ["GraphQuery"]

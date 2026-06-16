"""
Core value objects for graph retrieval.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List


class QueryType(Enum):
    ENTITY_RELATION = "entity_relation"
    MULTI_HOP = "multi_hop"
    SUBGRAPH = "subgraph"
    PATH_FINDING = "path_finding"
    CLUSTERING = "clustering"


@dataclass
class GraphQuery:
    query_type: QueryType
    source_entities: List[str] = field(default_factory=list)
    target_entities: List[str] = field(default_factory=list)
    relation_types: List[str] = field(default_factory=list)
    max_depth: int = 2
    max_nodes: int = 50
    constraints: Dict[str, Any] = field(default_factory=dict)


@dataclass
class GraphPath:
    nodes: List[Dict[str, Any]] = field(default_factory=list)
    relationships: List[Dict[str, Any]] = field(default_factory=list)
    path_length: int = 0
    relevance_score: float = 0.0
    path_type: str = ""


@dataclass
class KnowledgeSubgraph:
    central_nodes: List[Dict[str, Any]] = field(default_factory=list)
    connected_nodes: List[Dict[str, Any]] = field(default_factory=list)
    relationships: List[Dict[str, Any]] = field(default_factory=list)
    graph_metrics: Dict[str, float] = field(default_factory=dict)
    reasoning_chains: List[List[str] | str] = field(default_factory=list)




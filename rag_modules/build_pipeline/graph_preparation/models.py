"""Graph data models used by the build pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass(slots=True)
class GraphNode:
    """Structured graph node data loaded from Neo4j."""

    node_id: str
    labels: List[str] = field(default_factory=list)
    name: str = ""
    properties: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.node_id = str(self.node_id or "")
        self.labels = [str(label) for label in (self.labels or []) if str(label)]
        self.name = str(self.name or "")
        self.properties = dict(self.properties or {})


@dataclass(slots=True)
class GraphRelation:
    """Structured graph relationship data loaded from Neo4j."""

    start_node_id: str
    end_node_id: str
    relation_type: str
    properties: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.start_node_id = str(self.start_node_id or "")
        self.end_node_id = str(self.end_node_id or "")
        self.relation_type = str(self.relation_type or "")
        self.properties = dict(self.properties or {})


GraphNode.__module__ = "rag_modules.graph.data_preparation"
GraphRelation.__module__ = "rag_modules.graph.data_preparation"

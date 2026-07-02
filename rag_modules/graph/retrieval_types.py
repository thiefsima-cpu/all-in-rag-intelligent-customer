"""
Core value objects for graph retrieval.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from ..contracts import GraphQueryType
from ..runtime.json_types import JsonObject, coerce_json_object

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


@dataclass(slots=True, frozen=True)
class GraphNodeSnapshot:
    node_id: str = ""
    name: str = ""
    labels: tuple[str, ...] = ()
    category: str = ""
    properties: JsonObject = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, payload: Mapping[str, object]) -> "GraphNodeSnapshot":
        labels = payload.get("labels") or payload.get("originalLabels") or ()
        if isinstance(labels, str):
            label_tuple: tuple[str, ...] = (labels,)
        elif isinstance(labels, Sequence):
            label_tuple = tuple(str(label) for label in labels if str(label).strip())
        else:
            label_tuple = ()
        node_id = str(payload.get("nodeId") or payload.get("id") or "")
        name = str(payload.get("name") or payload.get("title") or node_id)
        category = str(payload.get("category") or "")
        properties = coerce_json_object(payload)
        return cls(
            node_id=node_id,
            name=name,
            labels=label_tuple,
            category=category,
            properties=properties,
        )

    def has_label(self, label: str) -> bool:
        return label in self.labels

    def to_dict(self) -> JsonObject:
        payload = dict(self.properties)
        payload.update(
            {
                "nodeId": self.node_id,
                "id": self.node_id,
                "name": self.name,
                "labels": list(self.labels),
            }
        )
        if self.category:
            payload["category"] = self.category
        return payload


@dataclass(slots=True, frozen=True)
class GraphRelationshipSnapshot:
    relation_type: str = ""
    start_node_id: str = ""
    end_node_id: str = ""
    properties: JsonObject = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, payload: Mapping[str, object]) -> "GraphRelationshipSnapshot":
        return cls(
            relation_type=str(payload.get("type") or ""),
            start_node_id=str(payload.get("startNodeId") or ""),
            end_node_id=str(payload.get("endNodeId") or ""),
            properties=coerce_json_object(payload),
        )

    def to_dict(self) -> JsonObject:
        payload = dict(self.properties)
        payload.update(
            {
                "type": self.relation_type,
                "startNodeId": self.start_node_id,
                "endNodeId": self.end_node_id,
            }
        )
        return payload


@dataclass
class GraphPath:
    nodes: list[GraphNodeSnapshot] = field(default_factory=list)
    relationships: list[GraphRelationshipSnapshot] = field(default_factory=list)
    path_length: int = 0
    relevance_score: float = 0.0
    path_type: str = ""


@dataclass
class KnowledgeSubgraph:
    central_nodes: list[GraphNodeSnapshot] = field(default_factory=list)
    connected_nodes: list[GraphNodeSnapshot] = field(default_factory=list)
    relationships: list[GraphRelationshipSnapshot] = field(default_factory=list)
    graph_metrics: dict[str, float] = field(default_factory=dict)
    reasoning_chains: list[list[str] | str] = field(default_factory=list)

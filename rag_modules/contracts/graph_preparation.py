"""Neutral graph-preparation data contracts shared across subsystems."""

from __future__ import annotations

from dataclasses import dataclass, field

from ..kernel.json_types import JsonObject


@dataclass(slots=True)
class GraphNode:
    """Structured graph node data loaded from Neo4j."""

    node_id: str
    labels: list[str] = field(default_factory=list)
    name: str = ""
    properties: JsonObject = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.node_id = str(self.node_id or "")
        self.labels = [str(label) for label in (self.labels or []) if str(label)]
        self.name = str(self.name or "")
        self.properties = dict(self.properties or {})


@dataclass(slots=True, frozen=True)
class GraphLoadCounts:
    """Counts of graph nodes loaded into preparation state."""

    total_entities: int = 0
    entity_groups: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> JsonObject:
        return {
            "total_entities": self.total_entities,
            "entity_groups": dict(self.entity_groups),
        }


@dataclass(slots=True)
class LoadedGraphData:
    """Domain-neutral graph collections returned by a build data loader."""

    primary_entities: list[GraphNode]
    primary_group: str
    related_entity_groups: dict[str, list[GraphNode]]

    def to_counts(self) -> GraphLoadCounts:
        group_counts = {
            self.primary_group: len(self.primary_entities),
            **{name: len(entities) for name, entities in self.related_entity_groups.items()},
        }
        return GraphLoadCounts(
            total_entities=sum(group_counts.values()),
            entity_groups=group_counts,
        )


@dataclass(slots=True, frozen=True)
class GraphPreparationStats:
    """Stable graph-preparation statistics with JSON serialization."""

    domain_name: str = ""
    total_entities: int = 0
    total_documents: int = 0
    total_chunks: int = 0
    entity_types: dict[str, int] = field(default_factory=dict)
    document_types: dict[str, int] = field(default_factory=dict)
    avg_content_length: float = 0.0
    avg_chunk_size: float = 0.0
    include_distributions: bool = False
    domain_metrics: JsonObject = field(default_factory=dict)

    def to_dict(self) -> JsonObject:
        payload: JsonObject = {
            "domain_name": self.domain_name,
            "total_entities": self.total_entities,
            "total_documents": self.total_documents,
            "total_chunks": self.total_chunks,
            "domain_metrics": dict(self.domain_metrics),
        }
        if not self.include_distributions:
            return payload
        payload.update(
            {
                "entity_types": dict(self.entity_types),
                "document_types": dict(self.document_types),
                "avg_content_length": self.avg_content_length,
                "avg_chunk_size": self.avg_chunk_size,
            }
        )
        return payload


__all__ = ["GraphLoadCounts", "GraphNode", "GraphPreparationStats", "LoadedGraphData"]

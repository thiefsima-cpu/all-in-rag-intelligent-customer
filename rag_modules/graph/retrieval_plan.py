"""
Executable graph retrieval plan.

QueryPlan describes user intent. GraphRetrievalPlan describes how the graph
executor should query Neo4j, including linked entities and evidence goals.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

from ..entity_linker import EntityLinkContext, LinkedEntity


@dataclass
class GraphRetrievalPlan:
    query_type: str
    source_entities: List[str]
    target_entities: List[str] = field(default_factory=list)
    relation_types: List[str] = field(default_factory=list)
    max_depth: int = 2
    max_nodes: int = 50
    constraints: Dict[str, Any] = field(default_factory=dict)
    linked_sources: List[LinkedEntity] = field(default_factory=list)
    linked_targets: List[LinkedEntity] = field(default_factory=list)
    evidence_goals: List[str] = field(default_factory=list)

    @property
    def source_node_ids(self) -> List[str]:
        return [entity.node_id for entity in self.linked_sources if entity.node_id]

    @property
    def target_node_ids(self) -> List[str]:
        return [entity.node_id for entity in self.linked_targets if entity.node_id]

    @property
    def source_terms(self) -> List[str]:
        values = [
            *(entity.name for entity in self.linked_sources if entity.name),
            *self.source_entities,
        ]
        return list(dict.fromkeys(str(value).strip() for value in values if str(value).strip()))

    @property
    def target_terms(self) -> List[str]:
        values = [
            *(entity.name for entity in self.linked_targets if entity.name),
            *self.target_entities,
        ]
        return list(dict.fromkeys(str(value).strip() for value in values if str(value).strip()))

    def to_trace(self) -> Dict[str, Any]:
        return {
            "query_type": self.query_type,
            "source_entities": self.source_entities,
            "target_entities": self.target_entities,
            "relation_types": self.relation_types,
            "max_depth": self.max_depth,
            "max_nodes": self.max_nodes,
            "linked_sources": [entity.to_dict() for entity in self.linked_sources],
            "linked_targets": [entity.to_dict() for entity in self.linked_targets],
            "evidence_goals": self.evidence_goals,
        }


class GraphPlanBuilder:
    """Build executable graph retrieval plans from graph query intent."""

    def __init__(self, entity_linker):
        self.entity_linker = entity_linker

    def build(self, graph_query, evidence_goals: List[str]) -> GraphRetrievalPlan:
        source_entities = list(dict.fromkeys(graph_query.source_entities or []))
        target_entities = list(dict.fromkeys(graph_query.target_entities or []))
        source_context = EntityLinkContext(
            query_type=getattr(graph_query.query_type, "value", str(graph_query.query_type)),
            relation_types=list(dict.fromkeys(graph_query.relation_types or [])),
            evidence_goals=list(dict.fromkeys(evidence_goals or [])),
            entity_role="source",
        )
        target_context = EntityLinkContext(
            query_type=getattr(graph_query.query_type, "value", str(graph_query.query_type)),
            relation_types=list(dict.fromkeys(graph_query.relation_types or [])),
            evidence_goals=list(dict.fromkeys(evidence_goals or [])),
            entity_role="target",
        )
        linked_sources = self.entity_linker.link_many(source_entities, context=source_context)
        linked_targets = self.entity_linker.link_many(target_entities, context=target_context)

        return GraphRetrievalPlan(
            query_type=getattr(graph_query.query_type, "value", str(graph_query.query_type)),
            source_entities=source_entities,
            target_entities=target_entities,
            relation_types=list(dict.fromkeys(graph_query.relation_types or [])),
            max_depth=max(1, min(int(graph_query.max_depth or 2), 4)),
            max_nodes=max(1, int(graph_query.max_nodes or 50)),
            constraints=graph_query.constraints or {},
            linked_sources=linked_sources,
            linked_targets=linked_targets,
            evidence_goals=evidence_goals,
        )



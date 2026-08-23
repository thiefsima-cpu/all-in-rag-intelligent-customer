"""Mutable state container for graph-preparation artifacts."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import List

from ...contracts.graph_preparation import GraphNode, LoadedGraphData
from ...kernel.documents import TextDocument
from ..ports import Neo4jDriverPort


class GraphDataLoader(ABC):
    @abstractmethod
    def load(self, driver: Neo4jDriverPort, *, database: str) -> LoadedGraphData: ...


class DomainDocumentBuilder(ABC):
    @abstractmethod
    def build(
        self,
        *,
        driver: Neo4jDriverPort,
        database: str,
        entities: Iterable[GraphNode],
    ) -> list[TextDocument]: ...


class DomainDocumentChunker(ABC):
    @abstractmethod
    def chunk(
        self,
        documents: Iterable[TextDocument],
        *,
        chunk_size: int,
        chunk_overlap: int,
    ) -> list[TextDocument]: ...


@dataclass(slots=True)
class GraphPreparationState:
    """Own the mutable in-memory state used during build-time preparation."""

    primary_entities: List[GraphNode] = field(default_factory=list)
    related_entity_groups: dict[str, List[GraphNode]] = field(default_factory=dict)
    documents: List[TextDocument] = field(default_factory=list)
    chunks: List[TextDocument] = field(default_factory=list)

    @property
    def entities(self) -> List[GraphNode]:
        return [
            *self.primary_entities,
            *(entity for group in self.related_entity_groups.values() for entity in group),
        ]


__all__ = [
    "DomainDocumentBuilder",
    "DomainDocumentChunker",
    "GraphDataLoader",
    "GraphPreparationState",
]

"""Domain-pack contracts consumed by domain-neutral RAG orchestration."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from ..kernel.documents import TextDocument
from ..kernel.json_types import JsonObject


@dataclass(frozen=True, slots=True)
class GraphNodeType:
    """One node type owned by a domain ontology."""

    label: str
    id_fields: tuple[str, ...]
    name_fields: tuple[str, ...]
    lookup_fields: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class GraphRelationType:
    """One directed relationship allowed by a domain ontology."""

    name: str
    source_labels: tuple[str, ...]
    target_labels: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DomainOntology:
    """Graph labels and relationships supplied by a domain pack."""

    primary_labels: tuple[str, ...]
    node_types: tuple[GraphNodeType, ...]
    relation_types: tuple[GraphRelationType, ...]

    @property
    def node_labels(self) -> tuple[str, ...]:
        return tuple(node.label for node in self.node_types)

    @property
    def entity_lookup_fields(self) -> tuple[str, ...]:
        return tuple(
            dict.fromkeys(
                field_name
                for node_type in self.node_types
                for field_name in (
                    *node_type.id_fields,
                    *node_type.name_fields,
                    *node_type.lookup_fields,
                )
                if field_name
            )
        )

    def node_type_for_labels(self, labels: tuple[str, ...]) -> GraphNodeType | None:
        labels_set = set(labels)
        return next(
            (node_type for node_type in self.node_types if node_type.label in labels_set),
            None,
        )


@dataclass(frozen=True, slots=True)
class ExtractedEntity:
    entity_id: str
    entity_name: str
    entity_type: str
    attributes: JsonObject = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ExtractedRelation:
    source_id: str
    relation_type: str
    target_id: str
    attributes: JsonObject = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class DomainExtraction:
    entities: tuple[ExtractedEntity, ...] = ()
    relations: tuple[ExtractedRelation, ...] = ()


class DomainDocumentMapper(ABC):
    """Map one domain record into a retrieval document."""

    @abstractmethod
    def map_document(self, payload: Mapping[str, Any]) -> TextDocument: ...

    @abstractmethod
    def extract(self, payload: Mapping[str, Any]) -> DomainExtraction: ...


@dataclass(frozen=True, slots=True)
class CitationProjection:
    """Safe public projection rules for evidence owned by a domain."""

    citation_label: str
    public_attribute_keys: tuple[str, ...] = ()
    expose_content: bool = True
    expose_entity_identity: bool = True
    expose_matched_terms: bool = True

    def project_attributes(self, metadata: Mapping[str, Any]) -> JsonObject:
        return {
            key: metadata[key]
            for key in self.public_attribute_keys
            if key in metadata and metadata[key] not in (None, "", [], {})
        }


@dataclass(frozen=True, slots=True)
class DomainPack:
    """Complete versioned behavior surface for one knowledge domain."""

    name: str
    version: str
    ontology: DomainOntology
    document_mapper: DomainDocumentMapper
    query_policy_bundle: str
    vector_collection_name: str
    citation_projection: CitationProjection
    evaluation_resource: str


__all__ = [
    "CitationProjection",
    "DomainDocumentMapper",
    "DomainExtraction",
    "DomainOntology",
    "DomainPack",
    "ExtractedEntity",
    "ExtractedRelation",
    "GraphNodeType",
    "GraphRelationType",
]

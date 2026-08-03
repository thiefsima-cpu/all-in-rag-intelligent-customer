"""Domain-pack contracts consumed by domain-neutral RAG orchestration."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable, Mapping
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
class DomainConstraintField:
    """One domain-owned query-constraint extension populated from a policy lexicon."""

    name: str
    term_group: str = ""
    first_match_only: bool = False


@dataclass(frozen=True, slots=True)
class DomainQueryConstraintSchema:
    """Allowed extension fields and lexical extraction rules for one domain."""

    fields: tuple[DomainConstraintField, ...] = ()
    excluded_term_fields: tuple[str, ...] = ()
    maximum_duration_field: str = ""

    @property
    def field_names(self) -> tuple[str, ...]:
        return tuple(field.name for field in self.fields)

    def project_extension(self, payload: Mapping[str, object]) -> JsonObject:
        nested = payload.get("extension")
        nested_payload = nested if isinstance(nested, Mapping) else {}
        legacy_time = payload.get("time")
        legacy_time_payload = legacy_time if isinstance(legacy_time, Mapping) else {}
        return {
            field_name: nested_payload.get(
                field_name,
                payload.get(field_name, legacy_time_payload.get(field_name)),
            )
            for field_name in self.field_names
            if nested_payload.get(
                field_name,
                payload.get(field_name, legacy_time_payload.get(field_name)),
            )
            not in (None, "", [], {})
        }


@dataclass(frozen=True, slots=True)
class DomainReasoningVocabulary:
    """Domain-owned labels and copy used to describe graph reasoning chains."""

    subject_fallback: str = "the target entities"
    comparison_labels: tuple[str, ...] = ()
    compositional_labels: tuple[tuple[str, str], ...] = ()
    semantic_effect_label: str = "semantic effects"
    semantic_node_labels: tuple[str, ...] = ()
    constraint_labels: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True, slots=True)
class DomainBuildDataView:
    """Domain-owned names for build-time entity groups and diagnostic projections."""

    primary_group: str
    related_groups: tuple[str, ...] = ()
    count_metrics: tuple[tuple[str, str], ...] = ()
    distribution_metrics: tuple[tuple[str, str], ...] = ()


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
    query_constraints: DomainQueryConstraintSchema
    reasoning_vocabulary: DomainReasoningVocabulary
    build_data_view: DomainBuildDataView
    build_adapter: str = "ontology"
    build_loader_factory: Callable[[], object] | None = None
    build_document_builder_factory: Callable[[], object] | None = None
    graph_import_resource: str = ""
    graph_import_replacements: tuple[tuple[str, str], ...] = ()
    semantic_graph_writer_factory: Callable[..., object] | None = None
    semantic_schema_enabled: bool = False
    semantic_schema_count_field: str = ""
    constraint_matcher_type: type[object] | None = None
    allow_domainless_graph_records: bool = False


__all__ = [
    "CitationProjection",
    "DomainBuildDataView",
    "DomainConstraintField",
    "DomainDocumentMapper",
    "DomainExtraction",
    "DomainOntology",
    "DomainPack",
    "DomainQueryConstraintSchema",
    "DomainReasoningVocabulary",
    "ExtractedEntity",
    "ExtractedRelation",
    "GraphNodeType",
    "GraphRelationType",
]

"""Canonical evidence document DTOs."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace

from ..kernel.documents import TextDocument
from ..kernel.json_types import JsonObject, coerce_float, coerce_json_object, coerce_str


@dataclass
class EvidenceDocument:
    content: str
    entity_id: str = ""
    entity_name: str = ""
    entity_type: str = ""
    node_id: str = ""
    node_type: str = ""
    score: float = 0.0
    search_type: str = ""
    search_method: str = ""
    retrieval_level: str = ""
    doc_id: str = ""
    source: str = "unknown"
    evidence_type: str = "text"
    matched_terms: list[str] = field(default_factory=list)
    graph_evidence: JsonObject = field(default_factory=dict)
    domain_graph_evidence: JsonObject = field(default_factory=dict)
    constraint_evidence: JsonObject = field(default_factory=dict)
    evidence_units: list[JsonObject] = field(default_factory=list)
    route_strategy: str = ""
    metadata: JsonObject = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.content = coerce_str(self.content)
        self.entity_id = coerce_str(self.entity_id or self.node_id)
        self.entity_name = coerce_str(self.entity_name)
        self.entity_type = coerce_str(self.entity_type or self.node_type)
        self.node_id = coerce_str(self.node_id)
        self.node_type = coerce_str(self.node_type or self.entity_type)
        self.score = coerce_float(self.score)
        self.search_type = coerce_str(self.search_type)
        self.search_method = coerce_str(self.search_method)
        self.retrieval_level = coerce_str(self.retrieval_level)
        self.doc_id = coerce_str(self.doc_id)
        self.source = coerce_str(self.source or self.search_method or self.search_type or "unknown")
        self.evidence_type = coerce_str(self.evidence_type or "text")
        self.matched_terms = [
            coerce_str(item).strip() for item in self.matched_terms if coerce_str(item).strip()
        ]
        self.graph_evidence = coerce_json_object(self.graph_evidence)
        self.domain_graph_evidence = coerce_json_object(self.domain_graph_evidence)
        self.constraint_evidence = coerce_json_object(self.constraint_evidence)
        self.evidence_units = [
            coerce_json_object(item) for item in self.evidence_units if isinstance(item, Mapping)
        ]
        self.route_strategy = coerce_str(self.route_strategy)
        self.metadata = coerce_json_object(self.metadata)

    @classmethod
    def from_dict(cls, payload: Mapping[str, object] | None) -> "EvidenceDocument":
        data = payload or {}
        raw_matched_terms = data.get("matched_terms")
        raw_evidence_units = data.get("evidence_units")
        return cls(
            content=coerce_str(data.get("content")),
            entity_id=coerce_str(data.get("entity_id")),
            entity_name=coerce_str(data.get("entity_name")),
            entity_type=coerce_str(data.get("entity_type")),
            node_id=coerce_str(data.get("node_id")),
            node_type=coerce_str(data.get("node_type")),
            score=coerce_float(data.get("score")),
            search_type=coerce_str(data.get("search_type")),
            search_method=coerce_str(data.get("search_method")),
            retrieval_level=coerce_str(data.get("retrieval_level")),
            doc_id=coerce_str(data.get("doc_id")),
            source=coerce_str(data.get("source")),
            evidence_type=coerce_str(data.get("evidence_type")),
            matched_terms=[
                coerce_str(item).strip() for item in raw_matched_terms if coerce_str(item).strip()
            ]
            if isinstance(raw_matched_terms, list)
            else [],
            graph_evidence=coerce_json_object(data.get("graph_evidence")),
            domain_graph_evidence=coerce_json_object(data.get("domain_graph_evidence")),
            constraint_evidence=coerce_json_object(data.get("constraint_evidence")),
            evidence_units=[
                coerce_json_object(item) for item in raw_evidence_units if isinstance(item, Mapping)
            ]
            if isinstance(raw_evidence_units, list)
            else [],
            route_strategy=coerce_str(data.get("route_strategy")),
            metadata=coerce_json_object(data.get("metadata")),
        )

    def with_search_fields(
        self,
        *,
        search_method: str | None = None,
        search_type: str | None = None,
        retrieval_level: str | None = None,
        score: float | None = None,
        metadata_updates: JsonObject | None = None,
    ) -> "EvidenceDocument":
        metadata = dict(self.metadata)
        if metadata_updates:
            metadata.update(metadata_updates)
        if search_method:
            metadata.setdefault("search_method", search_method)
        if search_type:
            metadata.setdefault("search_type", search_type)
        if retrieval_level:
            metadata.setdefault("retrieval_level", retrieval_level)
        if score is not None:
            metadata.setdefault("score", score)
        return replace(
            self,
            score=self.score if score is None else score,
            search_method=self.search_method or coerce_str(search_method),
            search_type=self.search_type or coerce_str(search_type),
            retrieval_level=self.retrieval_level or coerce_str(retrieval_level),
            metadata=metadata,
        )

    def document_key(self) -> str:
        node_id = self.node_id or coerce_str(
            self.metadata.get("entity_id")
            or self.entity_id
            or self.metadata.get("node_id")
            or self.metadata.get("parent_id")
            or self.metadata.get("recipe_id")
        )
        if node_id:
            return node_id
        entity_name = self.entity_name or coerce_str(
            self.metadata.get("entity_name") or self.metadata.get("recipe_name")
        )
        if entity_name:
            entity_type = (
                self.entity_type or coerce_str(self.metadata.get("entity_type")) or "entity"
            )
            return f"{entity_type.casefold()}::{entity_name}"
        return f"hash::{hash(self.content[:200])}"

    def to_metadata(self) -> JsonObject:
        return {
            "doc_id": self.doc_id,
            "entity_id": self.entity_id or self.node_id,
            "entity_name": self.entity_name,
            "entity_type": self.entity_type,
            "source": self.source,
            "score": self.score,
            "evidence_type": self.evidence_type,
            "matched_terms": list(self.matched_terms),
            "graph_evidence": dict(self.graph_evidence),
            "domain_graph_evidence": dict(self.domain_graph_evidence),
            "constraint_evidence": dict(self.constraint_evidence),
            "evidence_units": [dict(item) for item in self.evidence_units],
            "route_strategy": self.route_strategy,
        }

    def to_dict(self) -> JsonObject:
        return {
            "content": self.content,
            "entity_id": self.entity_id,
            "entity_name": self.entity_name,
            "entity_type": self.entity_type,
            "node_id": self.node_id,
            "node_type": self.node_type,
            "score": self.score,
            "search_type": self.search_type,
            "search_method": self.search_method,
            "retrieval_level": self.retrieval_level,
            "doc_id": self.doc_id,
            "source": self.source,
            "evidence_type": self.evidence_type,
            "matched_terms": list(self.matched_terms),
            "graph_evidence": dict(self.graph_evidence),
            "domain_graph_evidence": dict(self.domain_graph_evidence),
            "constraint_evidence": dict(self.constraint_evidence),
            "evidence_units": [dict(item) for item in self.evidence_units],
            "route_strategy": self.route_strategy,
            "metadata": dict(self.metadata),
        }


def matched_terms_from_metadata(metadata: JsonObject) -> list[str]:
    raw_matched_terms = metadata.get("matched_terms")
    if isinstance(raw_matched_terms, list):
        matched_terms = [coerce_str(item).strip() for item in raw_matched_terms]
        return list(dict.fromkeys(item for item in matched_terms if item))

    collected: list[str] = []
    for key in (
        "matched_keyword",
        "matched_entities",
        "matched_attributes",
        "matched_ingredients",
        "matched_steps",
    ):
        value = metadata.get(key)
        if isinstance(value, list):
            collected.extend(coerce_str(item).strip() for item in value if coerce_str(item).strip())
        elif value:
            collected.append(coerce_str(value).strip())
    return list(dict.fromkeys(item for item in collected if item))


def evidence_document_from_text_document(document: TextDocument) -> EvidenceDocument:
    metadata = coerce_json_object(document.metadata)
    raw_evidence_units = metadata.get("evidence_units")
    return EvidenceDocument(
        content=document.content,
        entity_id=coerce_str(
            metadata.get("entity_id")
            or metadata.get("node_id")
            or metadata.get("parent_id")
            or metadata.get("recipe_id")
        ),
        entity_name=coerce_str(
            metadata.get("entity_name") or metadata.get("recipe_name") or metadata.get("name")
        ),
        entity_type=coerce_str(metadata.get("entity_type") or metadata.get("node_type")),
        node_id=coerce_str(
            metadata.get("node_id")
            or metadata.get("entity_id")
            or metadata.get("parent_id")
            or metadata.get("recipe_id")
        ),
        node_type=coerce_str(metadata.get("node_type") or metadata.get("entity_type")),
        score=coerce_float(
            metadata.get("final_score")
            or metadata.get("relevance_score")
            or metadata.get("constraint_score")
            or metadata.get("score")
            or metadata.get("bm25_score")
        ),
        search_type=coerce_str(metadata.get("search_type")),
        search_method=coerce_str(metadata.get("search_method") or metadata.get("search_source")),
        retrieval_level=coerce_str(metadata.get("retrieval_level")),
        doc_id=coerce_str(metadata.get("doc_id")),
        source=coerce_str(
            metadata.get("source")
            or metadata.get("search_source")
            or metadata.get("search_method")
            or metadata.get("search_type")
            or "unknown"
        ),
        evidence_type=coerce_str(
            metadata.get("evidence_type")
            or metadata.get("search_type")
            or ("recipe" if metadata.get("recipe_name") else "text")
        ),
        matched_terms=matched_terms_from_metadata(metadata),
        graph_evidence=coerce_json_object(metadata.get("graph_evidence")),
        domain_graph_evidence=coerce_json_object(metadata.get("domain_graph_evidence")),
        constraint_evidence=coerce_json_object(metadata.get("constraint_evidence")),
        evidence_units=[
            coerce_json_object(item)
            for item in (raw_evidence_units if isinstance(raw_evidence_units, list) else [])
            if isinstance(item, Mapping)
        ],
        route_strategy=coerce_str(metadata.get("route_strategy")),
        metadata=metadata,
    )


__all__ = [
    "EvidenceDocument",
    "evidence_document_from_text_document",
    "matched_terms_from_metadata",
]

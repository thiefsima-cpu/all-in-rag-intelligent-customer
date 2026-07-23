"""Evidence data models."""

from __future__ import annotations

from dataclasses import dataclass, field

from ..contracts import EvidenceDocument, JsonObject, coerce_json_object


@dataclass
class EvidenceUnit:
    unit_id: str
    evidence_type: str
    claim: str
    source: str = "unknown"
    score: float = 0.0
    entity_id: str = ""
    entity_name: str = ""
    domain: str = ""
    relation_type: str = ""
    entities: list[str] = field(default_factory=list)
    is_graph_evidence: bool = False
    metadata: JsonObject = field(default_factory=dict)

    def to_dict(self) -> JsonObject:
        payload = {
            "unit_id": self.unit_id,
            "evidence_type": self.evidence_type,
            "claim": self.claim,
            "source": self.source,
            "score": self.score,
            "entity_id": self.entity_id,
            "entity_name": self.entity_name,
            "relation_type": self.relation_type,
            "entities": list(self.entities),
            "is_graph_evidence": self.is_graph_evidence,
            "metadata": dict(self.metadata or {}),
        }
        if self.domain == "recipe":
            payload.update({"recipe_id": self.entity_id, "recipe_name": self.entity_name})
        return coerce_json_object(payload)


@dataclass
class AggregatedEvidence:
    entity_id: str
    entity_name: str
    full_document: str = ""
    documents: list[EvidenceDocument] = field(default_factory=list)
    matched_terms: list[str] = field(default_factory=list)
    graph_paths: list[JsonObject] = field(default_factory=list)
    evidence_units: list[JsonObject] = field(default_factory=list)
    constraint_reasons: list[str] = field(default_factory=list)
    retrieval_sources: list[str] = field(default_factory=list)
    confidence: float = 0.0

    def to_dict(self) -> JsonObject:
        return {
            "entity_id": self.entity_id,
            "entity_name": self.entity_name,
            "matched_terms": list(self.matched_terms),
            "graph_paths": list(self.graph_paths),
            "evidence_units": [dict(unit) for unit in self.evidence_units],
            "constraint_reasons": list(self.constraint_reasons),
            "retrieval_sources": list(self.retrieval_sources),
            "confidence": self.confidence,
            "documents": [doc.to_metadata() for doc in self.documents],
        }

    @property
    def recipe_id(self) -> str:
        return self.entity_id

    @property
    def recipe_name(self) -> str:
        return self.entity_name

    @property
    def full_recipe_doc(self) -> str:
        return self.full_document

    @full_recipe_doc.setter
    def full_recipe_doc(self, value: str) -> None:
        self.full_document = str(value or "")


RecipeEvidence = AggregatedEvidence

__all__ = ["AggregatedEvidence", "EvidenceUnit", "RecipeEvidence"]

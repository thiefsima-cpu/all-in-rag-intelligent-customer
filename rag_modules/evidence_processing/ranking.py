"""Evidence ranking helpers."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace

from ..contracts import EvidenceDocument, JsonObject, coerce_float
from .extraction import extract_evidence_units
from .normalization import normalize_evidence_document


class EvidenceUnitRanker:
    """Lightweight query-aware scoring for documents that carry evidence units."""

    graph_bonus = 0.35
    relation_bonus = 0.2

    def rank_evidence_documents(
        self,
        query: str,
        documents: Sequence[EvidenceDocument],
    ) -> list[EvidenceDocument]:
        if not documents:
            return list(documents)
        scored = []
        for index, doc in enumerate(documents):
            score = self.document_score(query, doc)
            metadata = dict(doc.metadata or {})
            metadata["evidence_unit_score"] = score
            scored.append((score, index, replace(doc, metadata=metadata)))
        scored.sort(key=lambda item: (-item[0], item[1]))
        return [doc for _, _, doc in scored]

    def rank_documents(
        self,
        query: str,
        documents: Sequence[EvidenceDocument],
    ) -> list[EvidenceDocument]:
        return self.rank_evidence_documents(query, documents)

    def document_score(self, query: str, document: EvidenceDocument) -> float:
        evidence_doc = normalize_evidence_document(document)
        metadata = evidence_doc.metadata or {}
        base_score = coerce_float(
            metadata.get("final_score") or metadata.get("relevance_score") or metadata.get("score")
        )
        units = evidence_doc.evidence_units or extract_evidence_units(evidence_doc, metadata)
        if not units:
            return base_score
        unit_score = max(self.unit_score(query, unit) for unit in units)
        graph_count = sum(1 for unit in units if unit.get("is_graph_evidence"))
        return base_score + unit_score + min(graph_count, 3) * 0.05

    def unit_score(self, query: str, unit: JsonObject) -> float:
        claim = str(unit.get("claim") or "")
        raw_entities = unit.get("entities")
        entities = (
            [str(entity) for entity in raw_entities] if isinstance(raw_entities, list) else []
        )
        score = 0.0
        for token in self._query_terms(query):
            if token and token in claim:
                score += 0.08
            if any(token and token in entity for entity in entities):
                score += 0.06
        if unit.get("is_graph_evidence"):
            score += self.graph_bonus
        if unit.get("relation_type"):
            score += self.relation_bonus
        return min(score, 1.5)

    @staticmethod
    def _query_terms(query: str) -> list[str]:
        separators = ",.!?;: \n\r\t"
        text = str(query or "")
        for sep in separators:
            text = text.replace(sep, " ")
        terms = [part.strip() for part in text.split() if len(part.strip()) >= 2]
        return list(dict.fromkeys(terms))[:20]


__all__ = ["EvidenceUnitRanker"]

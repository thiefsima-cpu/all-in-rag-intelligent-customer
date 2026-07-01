"""Evidence ranking helpers."""

from __future__ import annotations

from typing import Any, Dict, List

from ..contracts import EvidenceDocument, ensure_evidence_documents
from .extraction import extract_evidence_units
from .models import PageDocumentLike
from .normalization import normalize_evidence_document


class EvidenceUnitRanker:
    """Lightweight query-aware scoring for documents that carry evidence units."""

    graph_bonus = 0.35
    relation_bonus = 0.2

    def rank_evidence_documents(
        self,
        query: str,
        documents: List[EvidenceDocument],
    ) -> List[EvidenceDocument]:
        if not documents:
            return documents
        scored = []
        for index, doc in enumerate(documents):
            score = self.document_score(query, doc)
            metadata = dict(doc.metadata or {})
            metadata["evidence_unit_score"] = score
            scored.append((score, index, doc.copy_with(metadata=metadata)))
        scored.sort(key=lambda item: (-item[0], item[1]))
        return [doc for _, _, doc in scored]

    def rank_documents(
        self,
        query: str,
        documents: List[PageDocumentLike | EvidenceDocument],
    ) -> List[EvidenceDocument]:
        evidence_docs = ensure_evidence_documents(documents)
        return self.rank_evidence_documents(query, evidence_docs)

    def document_score(self, query: str, doc: PageDocumentLike | EvidenceDocument) -> float:
        evidence_doc = normalize_evidence_document(doc)
        metadata = evidence_doc.metadata or {}
        base_score = float(
            metadata.get("final_score")
            or metadata.get("relevance_score")
            or metadata.get("score")
            or 0.0
        )
        units = evidence_doc.evidence_units or extract_evidence_units(evidence_doc, metadata)
        if not units:
            return base_score
        unit_score = max(self.unit_score(query, unit) for unit in units)
        graph_count = sum(1 for unit in units if unit.get("is_graph_evidence"))
        return base_score + unit_score + min(graph_count, 3) * 0.05

    def unit_score(self, query: str, unit: Dict[str, Any]) -> float:
        claim = str(unit.get("claim") or "")
        entities = [str(entity) for entity in unit.get("entities") or []]
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
    def _query_terms(query: str) -> List[str]:
        separators = ",.!?;: \n\r\t"
        text = str(query or "")
        for sep in separators:
            text = text.replace(sep, " ")
        terms = [part.strip() for part in text.split() if len(part.strip()) >= 2]
        return list(dict.fromkeys(terms))[:20]


__all__ = ["EvidenceUnitRanker"]

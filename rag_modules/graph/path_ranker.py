"""Ranking and de-duplication for graph retrieval evidence."""

from __future__ import annotations

from typing import Dict, List

from ..configuration.models import GraphSettings
from ..domain.shared.semantic_schema import SEMANTIC_RELATION_TYPES
from ..retrieval.contracts import EvidenceDocument


class GraphDocumentRanker:
    """Score graph evidence with configurable structural evidence weights."""

    def __init__(self, graph_settings: GraphSettings):
        self.base_weight = float(graph_settings.graph_rank_base_weight)
        self.semantic_relation_weight = float(graph_settings.graph_rank_semantic_relation_weight)
        self.evidence_unit_weight = float(graph_settings.graph_rank_evidence_unit_weight)
        self.relationship_weight = float(graph_settings.graph_rank_relationship_weight)
        self.recipe_presence_weight = float(graph_settings.graph_rank_recipe_presence_weight)
        self.query_overlap_weight = float(graph_settings.graph_rank_query_overlap_weight)

    def rank(self, documents: List[EvidenceDocument], query: str) -> List[EvidenceDocument]:
        return sorted(documents, key=lambda doc: self._score(doc, query), reverse=True)

    def dedupe(self, documents: List[EvidenceDocument]) -> List[EvidenceDocument]:
        grouped: Dict[str, EvidenceDocument] = {}
        order: List[str] = []

        for doc in documents:
            key = self._dedupe_key(doc)
            if key not in grouped:
                grouped[key] = doc
                order.append(key)
                continue

            current = grouped[key]
            current_metadata = dict(current.metadata or {})
            doc_metadata = dict(doc.metadata or {})
            current_metadata["relationship_count"] = max(
                int(current_metadata.get("relationship_count", 0) or 0),
                int(doc_metadata.get("relationship_count", 0) or 0),
            )
            current_metadata["relevance_score"] = max(
                float(current_metadata.get("relevance_score", 0.0) or 0.0),
                float(doc_metadata.get("relevance_score", 0.0) or 0.0),
            )
            merged_graph_evidence = list(current_metadata.get("merged_graph_evidence") or [])
            if doc.graph_evidence:
                merged_graph_evidence.append(doc.graph_evidence)
            if merged_graph_evidence:
                current_metadata["merged_graph_evidence"] = merged_graph_evidence
            merged_content = current.content
            if doc.content and doc.content not in merged_content:
                merged_content = current.content + "\n" + doc.content
            grouped[key] = current.copy_with(
                content=merged_content,
                score=max(current.score, doc.score),
                metadata=current_metadata,
            )

        return [grouped[key] for key in order]

    def _score(self, doc: EvidenceDocument, query: str) -> float:
        metadata = doc.metadata or {}
        score = float(
            metadata.get("relevance_score") or metadata.get("final_score") or doc.score or 0.0
        )
        score *= self.base_weight
        relationships = self._relationships(doc)
        semantic_rel_count = sum(
            1
            for rel in relationships
            if isinstance(rel, dict) and (rel.get("type") or "") in SEMANTIC_RELATION_TYPES
        )
        if not semantic_rel_count:
            semantic_rel_count = int(
                (doc.graph_evidence or {}).get("semantic_relationship_count") or 0
            )

        score += semantic_rel_count * self.semantic_relation_weight
        score += len(relationships) * self.relationship_weight
        score += len(doc.evidence_units or []) * self.evidence_unit_weight
        if metadata.get("recipe_node_ids") or metadata.get("recipe_names") or doc.recipe_name:
            score += self.recipe_presence_weight
        score += self._query_overlap(doc, query) * self.query_overlap_weight
        return score

    @staticmethod
    def _relationships(doc: EvidenceDocument) -> List[dict]:
        relationships: List[dict] = []
        graph_evidence = doc.graph_evidence or {}
        if isinstance(graph_evidence, dict):
            relationships.extend(
                [rel for rel in graph_evidence.get("relationships") or [] if isinstance(rel, dict)]
            )
        recipe_evidence = doc.recipe_graph_evidence or {}
        if isinstance(recipe_evidence, dict):
            relationships.extend(
                [
                    rel
                    for rel in recipe_evidence.get("semantic_relations") or []
                    if isinstance(rel, dict)
                ]
            )
        return relationships

    @staticmethod
    def _query_overlap(doc: EvidenceDocument, query: str) -> int:
        if not query:
            return 0
        metadata = doc.metadata or {}
        metadata_text = " ".join(
            str(value) for value in metadata.values() if isinstance(value, str)
        )
        text = f"{doc.content or ''} {metadata_text}"
        return sum(1 for char in set(query) if char.strip() and char in text)

    @staticmethod
    def _dedupe_key(doc: EvidenceDocument) -> str:
        metadata = doc.metadata or {}
        recipe_ids = metadata.get("recipe_node_ids") or []
        recipe_names = metadata.get("recipe_names") or []
        if recipe_ids:
            return "recipe_id::" + str(recipe_ids[0])
        if recipe_names:
            return "recipe_name::" + str(recipe_names[0])
        return doc.document_key()

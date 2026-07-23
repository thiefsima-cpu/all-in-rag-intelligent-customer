"""Ranking and de-duplication for graph retrieval evidence."""

from __future__ import annotations

from dataclasses import replace
from typing import Dict, List

from ..configuration.models import GraphSettings
from ..contracts import EvidenceDocument
from ..kernel.json_types import coerce_float, coerce_int
from ..kernel.semantic_schema import SEMANTIC_RELATION_TYPES


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
                coerce_int(current_metadata.get("relationship_count")),
                coerce_int(doc_metadata.get("relationship_count")),
            )
            current_metadata["relevance_score"] = max(
                coerce_float(current_metadata.get("relevance_score")),
                coerce_float(doc_metadata.get("relevance_score")),
            )
            raw_merged_evidence = current_metadata.get("merged_graph_evidence")
            merged_graph_evidence = (
                list(raw_merged_evidence) if isinstance(raw_merged_evidence, list) else []
            )
            if doc.graph_evidence:
                merged_graph_evidence.append(doc.graph_evidence)
            if merged_graph_evidence:
                current_metadata["merged_graph_evidence"] = merged_graph_evidence
            merged_content = current.content
            if doc.content and doc.content not in merged_content:
                merged_content = current.content + "\n" + doc.content
            grouped[key] = replace(
                current,
                content=merged_content,
                score=max(current.score, doc.score),
                metadata=current_metadata,
            )

        return [grouped[key] for key in order]

    def _score(self, doc: EvidenceDocument, query: str) -> float:
        metadata = doc.metadata or {}
        score = coerce_float(
            metadata.get("relevance_score") or metadata.get("final_score") or doc.score
        )
        score *= self.base_weight
        relationships = self._relationships(doc)
        semantic_rel_count = sum(
            1
            for rel in relationships
            if isinstance(rel, dict) and (rel.get("type") or "") in SEMANTIC_RELATION_TYPES
        )
        if not semantic_rel_count:
            semantic_rel_count = coerce_int(
                (doc.graph_evidence or {}).get("semantic_relationship_count")
            )

        score += semantic_rel_count * self.semantic_relation_weight
        score += len(relationships) * self.relationship_weight
        score += len(doc.evidence_units or []) * self.evidence_unit_weight
        if metadata.get("recipe_node_ids") or metadata.get("recipe_names") or doc.entity_name:
            score += self.recipe_presence_weight
        score += self._query_overlap(doc, query) * self.query_overlap_weight
        return score

    @staticmethod
    def _relationships(doc: EvidenceDocument) -> List[dict]:
        relationships: List[dict] = []
        graph_evidence = doc.graph_evidence or {}
        if isinstance(graph_evidence, dict):
            raw_relationships = graph_evidence.get("relationships")
            if isinstance(raw_relationships, list):
                relationships.extend(rel for rel in raw_relationships if isinstance(rel, dict))
        recipe_evidence = doc.domain_graph_evidence or {}
        if isinstance(recipe_evidence, dict):
            raw_relations = recipe_evidence.get("semantic_relations")
            if isinstance(raw_relations, list):
                relationships.extend(rel for rel in raw_relations if isinstance(rel, dict))
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
        recipe_ids = metadata.get("recipe_node_ids")
        recipe_names = metadata.get("recipe_names")
        if isinstance(recipe_ids, list) and recipe_ids:
            return "recipe_id::" + str(recipe_ids[0])
        if isinstance(recipe_names, list) and recipe_names:
            return "recipe_name::" + str(recipe_names[0])
        return doc.document_key()

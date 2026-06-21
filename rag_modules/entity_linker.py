"""
Entity linking for graph retrieval.

The graph executor should prefer stable node identifiers over broad string
matching. This linker resolves query entities to likely Neo4j nodes while still
keeping the original text as a fallback.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional

from neo4j import Driver

from .configuration.models import GraphSettings
from .query_understanding import (
    DEFAULT_ENTITY_LINKER_PREFERRED_LABELS,
    default_entity_linker_query_type_priorities,
    default_entity_linker_relation_priorities,
)

logger = logging.getLogger(__name__)


@dataclass
class LinkedEntity:
    text: str
    node_id: str = ""
    name: str = ""
    labels: List[str] = field(default_factory=list)
    category: str = ""
    confidence: float = 0.0
    match_reason: str = "unlinked"

    @property
    def resolved_value(self) -> str:
        return self.node_id or self.name or self.text

    def to_dict(self) -> Dict[str, Any]:
        return {
            "text": self.text,
            "node_id": self.node_id,
            "name": self.name,
            "labels": self.labels,
            "category": self.category,
            "confidence": self.confidence,
            "match_reason": self.match_reason,
        }


@dataclass
class EntityLinkContext:
    query_type: str = ""
    relation_types: List[str] = field(default_factory=list)
    evidence_goals: List[str] = field(default_factory=list)
    entity_role: str = "source"


class EntityLinker:
    """Resolve user/query entities to graph nodes."""

    def __init__(
        self,
        driver: Optional[Driver],
        database: str = "neo4j",
        graph_settings: Optional[GraphSettings] = None,
    ):
        self.driver = driver
        self.database = database
        self.graph_settings = graph_settings
        self.limit_per_entity = (
            int(graph_settings.entity_linker_limit_per_entity) if graph_settings else 4
        )
        self.min_confidence = (
            float(graph_settings.entity_linker_min_confidence) if graph_settings else 0.45
        )
        self.max_same_name_candidates = (
            int(graph_settings.entity_linker_max_same_name_candidates) if graph_settings else 2
        )
        self.preferred_labels = list(DEFAULT_ENTITY_LINKER_PREFERRED_LABELS)
        self.query_type_label_priorities = dict(
            graph_settings.entity_linker_query_type_label_priorities
            if graph_settings
            else default_entity_linker_query_type_priorities()
        )
        self.relation_label_priorities = dict(
            graph_settings.entity_linker_relation_label_priorities
            if graph_settings
            else default_entity_linker_relation_priorities()
        )

    def link_many(
        self,
        texts: Iterable[str],
        context: Optional[EntityLinkContext] = None,
    ) -> List[LinkedEntity]:
        unique_texts = [text for text in dict.fromkeys(str(v or "").strip() for v in texts) if text]
        if not unique_texts:
            return []
        if not self.driver:
            return [LinkedEntity(text=text, confidence=0.0) for text in unique_texts]

        linked: List[LinkedEntity] = []
        for text in unique_texts:
            candidates = self._lookup(text, context=context)
            if candidates:
                linked.extend(candidates)
            else:
                linked.append(LinkedEntity(text=text, confidence=0.0))
        return linked

    def _lookup(self, text: str, context: Optional[EntityLinkContext] = None) -> List[LinkedEntity]:
        query = """
        MATCH (n)
        WHERE n.nodeId = $text
           OR toString(n.name) = $text
           OR toString(n.name) CONTAINS $text
           OR $text CONTAINS toString(n.name)
           OR toString(n.category) CONTAINS $text
        WITH n,
             CASE
               WHEN n.nodeId = $text THEN 1.0
               WHEN toString(n.name) = $text THEN 0.95
               WHEN toString(n.name) CONTAINS $text THEN 0.78
               WHEN $text CONTAINS toString(n.name) THEN 0.70
               WHEN toString(n.category) CONTAINS $text THEN 0.55
               ELSE 0.0
             END AS match_score,
             COUNT { (n)--() } AS degree
        RETURN n.nodeId AS node_id,
               n.name AS name,
               n.category AS category,
               labels(n) AS labels,
               match_score,
               degree
        ORDER BY match_score DESC, degree DESC
        LIMIT $limit
        """
        try:
            driver = self.driver
            if driver is None:
                return []
            with driver.session(database=self.database) as session:
                records = session.run(query, text=text, limit=self.limit_per_entity)
                candidates = [self._from_record(text, record) for record in records]
        except Exception as exc:
            logger.warning("Entity linking failed for %s: %s", text, exc)
            return []

        filtered = [
            candidate for candidate in candidates if candidate.confidence >= self.min_confidence
        ]
        return self._prune_candidates(filtered, context=context)

    def _from_record(self, text: str, record) -> LinkedEntity:
        labels = list(record.get("labels") or [])
        match_score = float(record.get("match_score") or 0.0)
        degree = min(float(record.get("degree") or 0.0), 100.0) / 100.0
        label_bonus = 0.05 if any(label in self.preferred_labels for label in labels) else 0.0
        confidence = min(1.0, match_score + degree * 0.05 + label_bonus)
        if record.get("node_id") == text:
            reason = "node_id"
        elif record.get("name") == text:
            reason = "exact_name"
        elif record.get("name"):
            reason = "name_contains"
        else:
            reason = "category_contains"
        return LinkedEntity(
            text=text,
            node_id=str(record.get("node_id") or ""),
            name=str(record.get("name") or text),
            labels=labels,
            category=str(record.get("category") or ""),
            confidence=confidence,
            match_reason=reason,
        )

    def _prune_candidates(
        self,
        candidates: List[LinkedEntity],
        context: Optional[EntityLinkContext] = None,
    ) -> List[LinkedEntity]:
        if not candidates:
            return []

        deduped: List[LinkedEntity] = []
        seen = set()
        for candidate in sorted(
            candidates, key=lambda item: self._sort_key(item, context), reverse=True
        ):
            key = candidate.node_id or f"{candidate.name}::{','.join(candidate.labels)}"
            if key in seen:
                continue
            seen.add(key)
            deduped.append(candidate)

        exact = [
            candidate
            for candidate in deduped
            if candidate.match_reason in {"node_id", "exact_name"}
        ]
        preferred = exact or deduped

        pruned: List[LinkedEntity] = []
        same_name_counts: Dict[str, int] = {}
        for candidate in preferred:
            surface_key = (candidate.name or candidate.text).strip().lower()
            same_name_counts.setdefault(surface_key, 0)
            if same_name_counts[surface_key] >= self.max_same_name_candidates:
                continue
            same_name_counts[surface_key] += 1
            pruned.append(candidate)
            if len(pruned) >= self.limit_per_entity:
                break
        return pruned

    def _sort_key(self, candidate: LinkedEntity, context: Optional[EntityLinkContext]):
        exact_rank = (
            2
            if candidate.match_reason == "node_id"
            else 1
            if candidate.match_reason == "exact_name"
            else 0
        )
        label_rank = self._label_priority_rank(candidate.labels, context)
        recipe_bonus = 1 if "Recipe" in candidate.labels else 0
        return (exact_rank, label_rank, recipe_bonus, candidate.confidence)

    def _label_priority_rank(self, labels: List[str], context: Optional[EntityLinkContext]) -> int:
        priority_scores = self._priority_scores(context)
        if not priority_scores:
            return 0
        return max((priority_scores.get(label, 0) for label in labels), default=0)

    def _priority_scores(self, context: Optional[EntityLinkContext]) -> Dict[str, int]:
        scores: Dict[str, int] = {}
        if context:
            for relation_type in context.relation_types or []:
                self._apply_priority_list(
                    scores,
                    self.relation_label_priorities.get(str(relation_type), []),
                    base_weight=3,
                )
            if context.query_type:
                self._apply_priority_list(
                    scores,
                    self.query_type_label_priorities.get(str(context.query_type), []),
                    base_weight=2,
                )
        self._apply_priority_list(scores, self.preferred_labels, base_weight=1)
        return scores

    @staticmethod
    def _apply_priority_list(scores: Dict[str, int], labels: List[str], base_weight: int):
        label_count = len(labels or [])
        for index, label in enumerate(labels or []):
            if not label:
                continue
            scores[label] = scores.get(label, 0) + (label_count - index) * base_weight

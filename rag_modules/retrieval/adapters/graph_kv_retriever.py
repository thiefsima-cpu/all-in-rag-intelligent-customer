"""Graph key-value retriever with dynamic relevance scoring."""

from __future__ import annotations

import logging
import math
from typing import Any, Dict, List

from ..contracts import EvidenceDocument

logger = logging.getLogger(__name__)


def _match_score(query_term: str, candidate: str) -> float:
    q = query_term.lower()
    c = candidate.lower()
    if q == c:
        return 1.0
    if q in c:
        ratio = len(q) / max(len(c), 1)
        return 0.5 + 0.4 * ratio
    if c.startswith(q) or q.startswith(c):
        return 0.6
    return 0.0


def _richness_factor(kv_entry) -> float:
    content_len = len(getattr(kv_entry, "value_content", ""))
    return 0.2 * (1 - math.exp(-content_len / 300))


def _degree_factor(metadata: Dict[str, Any]) -> float:
    degree = metadata.get("degree", 0) or 0
    return 0.15 * min(degree / 10, 1.0)


def _best_key_score(query_term: str, keys: List[str]) -> float:
    return max((_match_score(query_term, key) for key in keys or []), default=0.0)


class GraphKVRetriever:
    """Two-tier retrieval over the in-memory graph key-value index."""

    def __init__(self, graph_indexing_module):
        self.index = graph_indexing_module

    def entity_search(self, keywords: List[str], top_k: int = 5) -> List[EvidenceDocument]:
        if not self.index or not keywords:
            return []

        docs: List[EvidenceDocument] = []
        seen: set = set()

        for keyword in keywords:
            entities = self.index.get_entities_by_key(keyword)
            for entity in entities:
                if entity.entity_name in seen:
                    continue
                seen.add(entity.entity_name)

                match_score = max(
                    _match_score(keyword, entity.entity_name),
                    _best_key_score(keyword, entity.index_keys),
                )
                if match_score <= 0:
                    continue

                score = round(
                    min(match_score * 0.6 + _richness_factor(entity) + _degree_factor(entity.metadata), 1.0),
                    4,
                )
                metadata = {
                    "node_id": entity.metadata.get("node_id", ""),
                    "recipe_name": entity.entity_name if entity.entity_type == "Recipe" else "",
                    "entity_name": entity.entity_name,
                    "entity_type": entity.entity_type,
                    "index_keys": entity.index_keys,
                    "relevance_score": score,
                    "score": score,
                    "retrieval_level": "entity",
                    "search_type": "graph_entity",
                    "search_method": "graph_entity",
                    "matched_keyword": keyword,
                    "source": "graph_entity",
                }
                docs.append(
                    EvidenceDocument(
                        content=entity.value_content,
                        node_id=str(entity.metadata.get("node_id", "")),
                        recipe_name=str(metadata.get("recipe_name") or ""),
                        node_type=entity.entity_type,
                        score=score,
                        search_type="graph_entity",
                        search_method="graph_entity",
                        retrieval_level="entity",
                        recipe_id=str(entity.metadata.get("node_id", "")),
                        source="graph_entity",
                        matched_terms=[keyword],
                        metadata=metadata,
                    )
                )

        docs.sort(key=lambda document: document.score, reverse=True)
        return docs[:top_k]

    def topic_search(self, keywords: List[str], top_k: int = 5) -> List[EvidenceDocument]:
        if not self.index or not keywords:
            return []

        docs: List[EvidenceDocument] = []
        seen: set = set()

        for keyword in keywords:
            relations = self.index.get_relations_by_key(keyword)
            for relation in relations:
                if relation.relation_id in seen:
                    continue
                seen.add(relation.relation_id)

                best_key_score = max((_match_score(keyword, key) for key in relation.index_keys), default=0.0)
                if best_key_score <= 0:
                    continue

                score = round(min(best_key_score * 0.5 + _richness_factor(relation) + 0.1, 1.0), 4)
                metadata = {
                    "source_entity": relation.source_entity,
                    "target_entity": relation.target_entity,
                    "relation_type": relation.relation_type,
                    "recipe_name": relation.metadata.get("source_name", ""),
                    "relevance_score": score,
                    "score": score,
                    "retrieval_level": "topic",
                    "search_type": "graph_topic",
                    "search_method": "graph_topic",
                    "matched_keyword": keyword,
                    "source_name": relation.metadata.get("source_name", ""),
                    "target_name": relation.metadata.get("target_name", ""),
                    "source": "graph_topic",
                }
                docs.append(
                    EvidenceDocument(
                        content=relation.value_content,
                        node_id=str(relation.source_entity or ""),
                        recipe_name=str(relation.metadata.get("source_name", "") or ""),
                        node_type="Relation",
                        score=score,
                        search_type="graph_topic",
                        search_method="graph_topic",
                        retrieval_level="topic",
                        recipe_id=str(relation.source_entity or ""),
                        source="graph_topic",
                        matched_terms=[keyword],
                        metadata=metadata,
                    )
                )

        docs.sort(key=lambda document: document.score, reverse=True)
        return docs[:top_k]

    def search(self, keywords: List[str], top_k: int = 5) -> List[EvidenceDocument]:
        entities = self.entity_search(keywords, top_k=top_k)
        topics = self.topic_search(keywords, top_k=top_k)
        combined: List[EvidenceDocument] = []
        entity_index = 0
        topic_index = 0
        while len(combined) < top_k and (entity_index < len(entities) or topic_index < len(topics)):
            if entity_index < len(entities):
                combined.append(entities[entity_index])
                entity_index += 1
            if topic_index < len(topics) and len(combined) < top_k:
                combined.append(topics[topic_index])
                topic_index += 1
        return combined

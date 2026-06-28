"""Evidence shaping helpers for dual-level retrieval."""

from __future__ import annotations

from typing import Callable, List

from ..contracts import EvidenceDocument


class DualLevelEvidenceService:
    """Shape graph-index and fallback candidates into consistent evidence documents."""

    def __init__(self, *, graph_indexing) -> None:
        self.graph_indexing = graph_indexing

    def enrich_entity_candidates(
        self,
        evidence_documents: List[EvidenceDocument],
        *,
        neighbor_lookup: Callable[[str, int], List[str]],
    ) -> List[EvidenceDocument]:
        results: List[EvidenceDocument] = []
        for evidence in evidence_documents:
            neighbors = neighbor_lookup(evidence.node_id, 2) if evidence.node_id else []
            content = evidence.content
            if neighbors:
                content += f"\n相关信息: {', '.join(neighbors)}"
            metadata = dict(evidence.metadata or {})
            metadata.update(
                {
                    "entity_name": metadata.get("entity_name", evidence.recipe_name),
                    "entity_type": metadata.get("entity_type", "Entity"),
                    "index_keys": metadata.get("index_keys", []),
                    "matched_keyword": metadata.get("matched_keyword", ""),
                    "search_method": metadata.get("search_method", "graph_entity"),
                    "search_type": metadata.get("search_type", "graph_entity"),
                }
            )
            results.append(
                evidence.copy_with(
                    content=content,
                    node_type=str(metadata.get("entity_type") or evidence.node_type or "Entity"),
                    score=float(metadata.get("relevance_score", evidence.score)),
                    search_type=str(
                        metadata.get("search_type") or evidence.search_type or "graph_entity"
                    ),
                    search_method=str(
                        metadata.get("search_method") or evidence.search_method or "graph_entity"
                    ),
                    retrieval_level="entity",
                    metadata=metadata,
                )
            )
        return results

    def enrich_topic_candidates(
        self, evidence_documents: List[EvidenceDocument]
    ) -> List[EvidenceDocument]:
        results: List[EvidenceDocument] = []
        for evidence in evidence_documents:
            metadata = dict(evidence.metadata or {})
            source_entity = str(metadata.get("source_entity") or evidence.node_id or "")
            source_kv = self.graph_indexing.entity_kv_store.get(source_entity)
            source_name = str(
                metadata.get("source_name") or (source_kv.entity_name if source_kv else "")
            )
            matched_keyword = str(metadata.get("matched_keyword") or "")
            content_parts = [
                f"主题: {matched_keyword}" if matched_keyword else "",
                evidence.content or "",
            ]
            if source_name:
                content_parts.append(f"相关菜品: {source_name}")
            if metadata.get("target_name"):
                content_parts.append(f"相关信息: {metadata['target_name']}")
            if source_kv and source_kv.entity_type == "Recipe":
                first_line = (source_kv.value_content or "").split("\n")[0]
                if first_line:
                    content_parts.append(f"菜谱详情: {first_line}")

            enriched_metadata = dict(metadata)
            enriched_metadata.update(
                {
                    "relation_type": metadata.get("relation_type", ""),
                    "source_entity": source_entity,
                    "target_entity": metadata.get("target_entity", ""),
                    "source_name": source_name,
                    "target_name": metadata.get("target_name", ""),
                    "matched_keyword": matched_keyword,
                    "search_method": metadata.get("search_method", "graph_topic"),
                    "search_type": metadata.get("search_type", "graph_topic"),
                }
            )
            results.append(
                evidence.copy_with(
                    content="\n".join(part for part in content_parts if part),
                    node_id=source_entity,
                    recipe_name=source_name,
                    node_type=source_kv.entity_type
                    if source_kv
                    else evidence.node_type or "Relation",
                    score=float(metadata.get("relevance_score", evidence.score or 0.0)),
                    search_type=str(enriched_metadata["search_type"]),
                    search_method=str(enriched_metadata["search_method"]),
                    retrieval_level="topic",
                    metadata=enriched_metadata,
                )
            )
        return results

    def category_topic_candidates(self, topic_keywords: List[str]) -> List[EvidenceDocument]:
        results: List[EvidenceDocument] = []
        for keyword in topic_keywords:
            entities = self.graph_indexing.get_entities_by_key(keyword)
            for entity in entities:
                if entity.entity_type != "Recipe":
                    continue
                results.append(
                    EvidenceDocument(
                        content=f"主题分类: {keyword}\n{entity.value_content}",
                        node_id=str(entity.metadata.get("node_id", "")),
                        recipe_name=entity.entity_name,
                        node_type=entity.entity_type,
                        score=0.85,
                        search_type="topic_category",
                        search_method="category_match",
                        retrieval_level="topic",
                        source="category_match",
                        matched_terms=[keyword],
                        metadata={
                            "entity_name": entity.entity_name,
                            "entity_type": entity.entity_type,
                            "matched_keyword": keyword,
                            "source": "category_match",
                        },
                    )
                )
        return results

    @staticmethod
    def sort_and_dedupe(documents: List[EvidenceDocument], *, top_k: int) -> List[EvidenceDocument]:
        deduped: List[EvidenceDocument] = []
        seen = set()
        for item in sorted(documents, key=lambda candidate: candidate.score, reverse=True):
            key = item.document_key()
            if key in seen:
                continue
            seen.add(key)
            deduped.append(item)
        return deduped[:top_k]

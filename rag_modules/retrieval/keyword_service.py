"""
Keyword extraction helpers for hybrid retrieval.
"""

from __future__ import annotations

import logging
from typing import List, Tuple

from ..contracts import QuerySemanticRuntimeSettings
from ..kernel.json_types import as_string_list
from ..query_understanding.features import normalize_graph_sources
from ..query_understanding.graph_intent import infer_query_semantic_profile
from ..query_understanding.registry import relation_index_terms

logger = logging.getLogger(__name__)


class QueryKeywordExtractor:
    """Extract entity- and topic-level keywords from a user query."""

    def __init__(self, semantic_settings: QuerySemanticRuntimeSettings):
        self.semantic_settings = semantic_settings

    def extract(self, query: str) -> Tuple[List[str], List[str]]:
        profile = infer_query_semantic_profile(query, settings=self.semantic_settings)
        constraints = profile.constraints or {}

        entity_keywords = normalize_graph_sources(
            [
                *profile.source_entities,
                *profile.target_entities,
                *profile.entity_keywords,
            ]
        )
        if not entity_keywords:
            entity_keywords = normalize_graph_sources(profile.entity_keywords or [])

        topic_keywords = self.dedupe_terms(
            [
                *profile.topic_keywords,
                *profile.recommendation_hits,
                *as_string_list(constraints.get("entity_terms")),
                *_constraint_extension_terms(constraints.get("extension")),
            ]
        )
        for relation_type in profile.relation_types:
            topic_keywords.extend(relation_index_terms(relation_type))
        topic_keywords = self.dedupe_terms(topic_keywords)

        if not entity_keywords:
            entity_keywords = self.dedupe_terms(profile.entity_keywords or [])
        if not topic_keywords:
            topic_keywords = self.dedupe_terms(
                [
                    *profile.recommendation_hits,
                    *_constraint_extension_terms(constraints.get("extension")),
                ]
            )

        logger.info(
            "Keyword extraction complete: entity=%s topic=%s",
            entity_keywords,
            topic_keywords,
        )
        return entity_keywords[:8], topic_keywords[:8]

    @staticmethod
    def dedupe_terms(terms: List[str]) -> List[str]:
        seen = set()
        output: List[str] = []
        for term in terms:
            value = (term or "").strip()
            if not value or value in seen:
                continue
            seen.add(value)
            output.append(value)
        return output


def _constraint_extension_terms(value: object) -> list[str]:
    if not isinstance(value, dict):
        return []
    return [term for item in value.values() for term in as_string_list(item)]

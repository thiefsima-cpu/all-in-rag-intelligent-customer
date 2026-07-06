"""Lexical helpers and intent markers for query understanding."""

from __future__ import annotations

import re
import warnings
from typing import List, Sequence

from .registry import (
    QueryUnderstandingRegistry,
    contains_any,
    dedupe_preserve_order,
    normalize_query_text,
    query_registry,
)


def _active_registry(registry: QueryUnderstandingRegistry | None) -> QueryUnderstandingRegistry:
    return registry or query_registry()


def remove_subsumed_tokens(tokens: Sequence[str]) -> List[str]:
    items = dedupe_preserve_order(tokens)
    result: List[str] = []
    for token in items:
        if any(token != other and token in other for other in items):
            continue
        result.append(token)
    return result


def matched_terms(text: str, terms: Sequence[str]) -> List[str]:
    return [term for term in terms if term and term in text]


def regex_group_matches(
    text: str,
    group_name: str,
    *,
    registry: QueryUnderstandingRegistry | None = None,
) -> bool:
    active_registry = _active_registry(registry)
    return any(
        re.search(pattern, text)
        for pattern in active_registry.policy.lexicon.regex_group(group_name)
    )


def apply_cleanup_patterns(
    text: str,
    group_name: str,
    *,
    registry: QueryUnderstandingRegistry | None = None,
) -> str:
    active_registry = _active_registry(registry)
    value = text
    for pattern in active_registry.policy.lexicon.regex_group(group_name):
        value = re.sub(pattern, "", value)
    return value


def has_recommendation_intent(
    query: str,
    *,
    registry: QueryUnderstandingRegistry | None = None,
) -> bool:
    active_registry = _active_registry(registry)
    if contains_any(query, active_registry.explicit_recommendation_markers):
        return True
    if contains_any(query, active_registry.structural_reasoning_markers):
        return False
    if contains_any(query, active_registry.ambiguous_recommendation_markers):
        return True
    return regex_group_matches(query, "recommendation_patterns", registry=active_registry)


def has_filtering_intent(
    query: str,
    *,
    registry: QueryUnderstandingRegistry | None = None,
) -> bool:
    active_registry = _active_registry(registry)
    if contains_any(query, active_registry.filtering_markers):
        return True
    if any(
        re.search(pattern, query)
        for pattern in active_registry.policy.lexicon.regex_group("time_minutes_patterns")
    ):
        return True
    if any(
        re.search(pattern, query)
        for pattern in active_registry.policy.lexicon.regex_group("time_hours_patterns")
    ):
        return True
    return contains_any(
        query,
        active_registry.policy.lexicon.regex_group("time_half_hour_patterns"),
    )


def clean_entity_phrase(
    text: str,
    *,
    registry: QueryUnderstandingRegistry | None = None,
) -> str:
    active_registry = _active_registry(registry)
    value = normalize_query_text(text)
    if not value:
        return ""
    value = apply_cleanup_patterns(
        value,
        "entity_cleanup_prefix_patterns",
        registry=active_registry,
    )
    value = apply_cleanup_patterns(
        value,
        "graph_context_suffix_patterns",
        registry=active_registry,
    )
    value = apply_cleanup_patterns(
        value,
        "entity_cleanup_suffix_patterns",
        registry=active_registry,
    )
    value = re.sub(r"^[^\u4e00-\u9fffA-Za-z0-9]+", "", value)
    value = re.sub(r"[^\u4e00-\u9fffA-Za-z0-9]+$", "", value)
    return value.strip()


def is_stopword_like(
    text: str,
    *,
    registry: QueryUnderstandingRegistry | None = None,
) -> bool:
    active_registry = _active_registry(registry)
    return text in active_registry.query_stopwords or text in active_registry.graph_generic_terms


def looks_like_entity(
    text: str,
    *,
    registry: QueryUnderstandingRegistry | None = None,
) -> bool:
    active_registry = _active_registry(registry)
    value = str(text or "").strip()
    if len(value) < 2 or len(value) > 24:
        return False
    if is_stopword_like(value, registry=active_registry):
        return False
    if value.isdigit():
        return False
    if (
        value in active_registry.relation_markers
        or value in active_registry.structural_reasoning_markers
    ):
        return False
    if (
        contains_any(value, active_registry.graph_generic_terms)
        or contains_any(value, active_registry.recommendation_markers)
        or contains_any(value, active_registry.filtering_markers)
        or contains_any(value, active_registry.time_markers)
    ) and value not in active_registry.semantic_node_terms:
        return False
    return True


def extract_query_tokens(
    query: str,
    *,
    registry: QueryUnderstandingRegistry | None = None,
) -> List[str]:
    active_registry = _active_registry(registry)
    normalized = normalize_query_text(query)
    segmented_text = re.sub(r"[^\u4e00-\u9fffA-Za-z0-9]+", " ", normalized)
    try:
        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore",
                message="pkg_resources is deprecated as an API.*",
                category=UserWarning,
                module=r"jieba\._compat",
            )
            import jieba

        raw_tokens = [part.strip() for part in jieba.lcut(segmented_text) if part.strip()]
    except Exception:
        raw_tokens = [part.strip() for part in segmented_text.split(" ") if part.strip()]

    matched = dedupe_preserve_order(
        [
            *matched_terms(normalized, active_registry.texture_effect_terms),
            *matched_terms(normalized, active_registry.flavor_terms),
            *matched_terms(normalized, active_registry.technique_terms),
            *matched_terms(normalized, active_registry.health_terms),
            *matched_terms(normalized, active_registry.cuisine_style_terms),
            *matched_terms(normalized, active_registry.ingredient_category_terms),
        ]
    )

    cleaned: List[str] = []
    for token in [*raw_tokens, *matched]:
        value = clean_entity_phrase(token, registry=active_registry)
        if not value:
            continue
        if len(value) == 1 and not re.search(r"[A-Za-z0-9]", value):
            continue
        if is_stopword_like(value, registry=active_registry):
            continue
        cleaned.append(value)

    return remove_subsumed_tokens(cleaned)


def fallback_keywords(
    query: str,
    *,
    registry: QueryUnderstandingRegistry | None = None,
) -> List[str]:
    return extract_query_tokens(query, registry=registry)


__all__ = [
    "apply_cleanup_patterns",
    "clean_entity_phrase",
    "extract_query_tokens",
    "fallback_keywords",
    "has_filtering_intent",
    "has_recommendation_intent",
    "is_stopword_like",
    "looks_like_entity",
    "matched_terms",
    "regex_group_matches",
    "remove_subsumed_tokens",
]

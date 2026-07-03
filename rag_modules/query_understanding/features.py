"""Lexical feature extraction and heuristic constraint parsing."""

from __future__ import annotations

import re
import warnings
from typing import Any, Dict, List, Sequence, Tuple

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


def pairwise_entity_matches(
    query: str,
    *,
    registry: QueryUnderstandingRegistry | None = None,
) -> List[Tuple[str, str]]:
    active_registry = _active_registry(registry)
    matches: List[Tuple[str, str]] = []
    for pattern in active_registry.policy.lexicon.regex_group("pairwise_entity_patterns"):
        for left, right in re.findall(pattern, query):
            left_text = clean_entity_phrase(left, registry=active_registry)
            right_text = clean_entity_phrase(right, registry=active_registry)
            if looks_like_entity(left_text, registry=active_registry) and looks_like_entity(
                right_text,
                registry=active_registry,
            ):
                matches.append((left_text, right_text))
    return matches


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


def fallback_entity_phrases(
    query: str,
    *,
    registry: QueryUnderstandingRegistry | None = None,
) -> List[str]:
    active_registry = _active_registry(registry)
    normalized = normalize_query_text(query)
    if not normalized:
        return []

    phrases: List[str] = []
    for left, right in pairwise_entity_matches(normalized, registry=active_registry):
        phrases.extend([left, right])

    for marker in active_registry.entity_phrase_markers:
        if marker not in normalized:
            continue
        left, right = normalized.split(marker, 1)
        left_text = clean_entity_phrase(left, registry=active_registry)
        right_text = clean_entity_phrase(right, registry=active_registry)
        if looks_like_entity(left_text, registry=active_registry):
            phrases.append(left_text)
        if marker in active_registry.entity_target_markers and looks_like_entity(
            right_text,
            registry=active_registry,
        ):
            phrases.append(right_text)

    phrases.extend(matched_terms(normalized, active_registry.texture_effect_terms))
    phrases.extend(matched_terms(normalized, active_registry.flavor_terms))
    return dedupe_preserve_order(phrases)


def extract_entity_candidates(
    query: str,
    *,
    registry: QueryUnderstandingRegistry | None = None,
) -> List[str]:
    active_registry = _active_registry(registry)
    normalized = normalize_query_text(query)
    candidates = dedupe_preserve_order(
        [
            *fallback_entity_phrases(normalized, registry=active_registry),
            *extract_query_tokens(normalized, registry=active_registry),
            *matched_terms(normalized, active_registry.texture_effect_terms),
            *matched_terms(normalized, active_registry.flavor_terms),
        ]
    )
    filtered: List[str] = []
    for candidate in candidates:
        if candidate in active_registry.graph_generic_terms:
            continue
        if candidate in active_registry.structural_reasoning_markers:
            continue
        if looks_like_entity(candidate, registry=active_registry):
            filtered.append(candidate)
    return normalize_graph_sources(filtered, registry=active_registry)


def normalize_graph_sources(
    values: Sequence[str],
    *,
    registry: QueryUnderstandingRegistry | None = None,
) -> List[str]:
    active_registry = _active_registry(registry)
    normalized: List[str] = []
    for value in values or []:
        text = str(value or "").strip()
        if not text:
            continue
        for prefix in active_registry.graph_source_prefixes:
            if text.startswith(prefix) and len(text) > len(prefix):
                text = text[len(prefix) :]
        for suffix in active_registry.graph_source_suffixes:
            if text.endswith(suffix) and len(text) > len(suffix):
                text = text[: -len(suffix)]
        text = clean_entity_phrase(text, registry=active_registry)
        if not looks_like_entity(text, registry=active_registry):
            continue
        if text not in normalized:
            normalized.append(text)
    return remove_subsumed_tokens(normalized)


def infer_graph_query_type(
    query: str,
    *,
    registry: QueryUnderstandingRegistry | None = None,
) -> str:
    active_registry = _active_registry(registry)
    normalized = normalize_query_text(query)
    if not normalized:
        return "entity_relation"
    if contains_any(normalized, active_registry.path_markers) or pairwise_entity_matches(
        normalized,
        registry=active_registry,
    ):
        return "path_finding"
    if contains_any(normalized, active_registry.subgraph_markers):
        return "subgraph"
    if contains_any(normalized, active_registry.clustering_markers):
        return "clustering"
    if contains_any(normalized, active_registry.relation_markers) or contains_any(
        normalized, active_registry.structural_reasoning_markers
    ):
        return "multi_hop"
    return "entity_relation"


def infer_relation_types(
    query: str,
    *,
    registry: QueryUnderstandingRegistry | None = None,
) -> List[str]:
    active_registry = _active_registry(registry)
    normalized = normalize_query_text(query)
    relation_types: List[str] = []
    for relation_type, markers in active_registry.relation_query_markers.items():
        if relation_type in active_registry.graph_relation_types and contains_any(
            normalized,
            markers,
        ):
            relation_types.append(relation_type)
    return dedupe_preserve_order(relation_types)


def extract_minutes(
    query: str,
    *,
    registry: QueryUnderstandingRegistry | None = None,
) -> int | None:
    active_registry = _active_registry(registry)
    for pattern in active_registry.policy.lexicon.regex_group("time_minutes_patterns"):
        match = re.search(pattern, query)
        if match:
            return int(round(float(match.group(1))))
    for pattern in active_registry.policy.lexicon.regex_group("time_hours_patterns"):
        match = re.search(pattern, query)
        if match:
            return int(round(float(match.group(1)) * 60))
    if contains_any(query, active_registry.policy.lexicon.regex_group("time_half_hour_patterns")):
        return 30
    return None


def extract_style(
    query: str,
    *,
    registry: QueryUnderstandingRegistry | None = None,
) -> str:
    active_registry = _active_registry(registry)
    for style in active_registry.cuisine_style_terms:
        if style in query:
            return style
    return ""


def extract_difficulty(
    query: str,
    *,
    registry: QueryUnderstandingRegistry | None = None,
) -> str:
    active_registry = _active_registry(registry)
    for difficulty in active_registry.difficulty_terms:
        if difficulty in query:
            return difficulty
    return ""


def extract_excluded_terms(
    query: str,
    *,
    registry: QueryUnderstandingRegistry | None = None,
) -> List[str]:
    active_registry = _active_registry(registry)
    excluded: List[str] = []
    for pattern in active_registry.policy.lexicon.regex_group("excluded_term_patterns"):
        for match in re.findall(pattern, query):
            value = clean_entity_phrase(match, registry=active_registry)
            if looks_like_entity(value, registry=active_registry):
                excluded.append(value)
    return dedupe_preserve_order(excluded)


def infer_query_constraints(
    query: str,
    *,
    registry: QueryUnderstandingRegistry | None = None,
) -> Dict[str, Any]:
    active_registry = _active_registry(registry)
    normalized = normalize_query_text(query)
    query_type = infer_graph_query_type(normalized, registry=active_registry)
    recommendation_intent = has_recommendation_intent(normalized, registry=active_registry)
    filtering_intent = has_filtering_intent(normalized, registry=active_registry)
    selection_intent = recommendation_intent or filtering_intent

    explicit_minutes = extract_minutes(normalized, registry=active_registry)
    excluded_terms = extract_excluded_terms(normalized, registry=active_registry)
    style = extract_style(normalized, registry=active_registry) if selection_intent else ""
    difficulty = (
        extract_difficulty(normalized, registry=active_registry) if selection_intent else ""
    )
    category_hits = (
        matched_terms(normalized, active_registry.ingredient_category_terms)
        if selection_intent
        else []
    )
    health_hits = (
        matched_terms(normalized, active_registry.health_terms) if selection_intent else []
    )

    if (
        query_type in {"path_finding", "multi_hop", "subgraph", "clustering"}
        and not selection_intent
    ):
        category_hits = []
        health_hits = []
        style = ""
        difficulty = ""

    return {
        "include_terms": dedupe_preserve_order([*category_hits, *([style] if style else [])]),
        "exclude_terms": excluded_terms,
        "ingredients": [],
        "excluded_ingredients": excluded_terms,
        "cuisine_terms": [style] if style else [],
        "excluded_cuisine_terms": [],
        "category_terms": dedupe_preserve_order(category_hits),
        "health_terms": dedupe_preserve_order(health_hits),
        "preference_terms": dedupe_preserve_order([*([difficulty] if difficulty else [])]),
        "time": {
            "max_total_minutes": explicit_minutes if filtering_intent else None,
            "max_prep_minutes": None,
            "max_cook_minutes": None,
        },
        "needs_recipe_recommendation": bool(recommendation_intent),
    }


__all__ = [
    "apply_cleanup_patterns",
    "clean_entity_phrase",
    "extract_difficulty",
    "extract_entity_candidates",
    "extract_excluded_terms",
    "extract_minutes",
    "extract_query_tokens",
    "extract_style",
    "fallback_entity_phrases",
    "fallback_keywords",
    "has_filtering_intent",
    "has_recommendation_intent",
    "infer_graph_query_type",
    "infer_query_constraints",
    "infer_relation_types",
    "looks_like_entity",
    "matched_terms",
    "normalize_graph_sources",
    "pairwise_entity_matches",
    "regex_group_matches",
    "remove_subsumed_tokens",
]

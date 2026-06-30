"""Lexical feature extraction and heuristic constraint parsing."""

from __future__ import annotations

import re
import warnings
from typing import Any, Dict, List, Sequence, Tuple

from .registry import (
    AMBIGUOUS_RECOMMENDATION_MARKERS,
    CUISINE_STYLE_TERMS,
    DIFFICULTY_TERMS,
    ENTITY_PHRASE_MARKERS,
    ENTITY_TARGET_MARKERS,
    EXPLICIT_RECOMMENDATION_MARKERS,
    FILTERING_MARKERS,
    FLAVOR_TERMS,
    GRAPH_GENERIC_TERMS,
    GRAPH_RELATION_TYPES,
    GRAPH_SOURCE_PREFIXES,
    GRAPH_SOURCE_SUFFIXES,
    HEALTH_TERMS,
    INGREDIENT_CATEGORY_TERMS,
    PATH_MARKERS,
    POLICY,
    QUERY_STOPWORDS,
    RECOMMENDATION_MARKERS,
    RELATION_MARKERS,
    RELATION_QUERY_MARKERS,
    SEMANTIC_NODE_TERMS,
    STRUCTURAL_REASONING_MARKERS,
    SUBGRAPH_MARKERS,
    TECHNIQUE_TERMS,
    TEXTURE_EFFECT_TERMS,
    TIME_MARKERS,
    contains_any,
    dedupe_preserve_order,
    normalize_query_text,
)


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


def regex_group_matches(text: str, group_name: str) -> bool:
    return any(re.search(pattern, text) for pattern in POLICY.lexicon.regex_group(group_name))


def apply_cleanup_patterns(text: str, group_name: str) -> str:
    value = text
    for pattern in POLICY.lexicon.regex_group(group_name):
        value = re.sub(pattern, "", value)
    return value


def has_recommendation_intent(query: str) -> bool:
    if contains_any(query, EXPLICIT_RECOMMENDATION_MARKERS):
        return True
    if contains_any(query, STRUCTURAL_REASONING_MARKERS):
        return False
    if contains_any(query, AMBIGUOUS_RECOMMENDATION_MARKERS):
        return True
    return regex_group_matches(query, "recommendation_patterns")


def has_filtering_intent(query: str) -> bool:
    if contains_any(query, FILTERING_MARKERS):
        return True
    if any(
        re.search(pattern, query)
        for pattern in POLICY.lexicon.regex_group("time_minutes_patterns")
    ):
        return True
    if any(
        re.search(pattern, query)
        for pattern in POLICY.lexicon.regex_group("time_hours_patterns")
    ):
        return True
    return contains_any(query, POLICY.lexicon.regex_group("time_half_hour_patterns"))


def clean_entity_phrase(text: str) -> str:
    value = normalize_query_text(text)
    if not value:
        return ""
    value = apply_cleanup_patterns(value, "entity_cleanup_prefix_patterns")
    value = apply_cleanup_patterns(value, "graph_context_suffix_patterns")
    value = apply_cleanup_patterns(value, "entity_cleanup_suffix_patterns")
    value = re.sub(r"^[^\u4e00-\u9fffA-Za-z0-9]+", "", value)
    value = re.sub(r"[^\u4e00-\u9fffA-Za-z0-9]+$", "", value)
    return value.strip()


def is_stopword_like(text: str) -> bool:
    return text in QUERY_STOPWORDS or text in GRAPH_GENERIC_TERMS


def looks_like_entity(text: str) -> bool:
    value = str(text or "").strip()
    if len(value) < 2 or len(value) > 24:
        return False
    if is_stopword_like(value):
        return False
    if value.isdigit():
        return False
    if value in RELATION_MARKERS or value in STRUCTURAL_REASONING_MARKERS:
        return False
    if (
        contains_any(value, GRAPH_GENERIC_TERMS)
        or contains_any(value, RECOMMENDATION_MARKERS)
        or contains_any(value, FILTERING_MARKERS)
        or contains_any(value, TIME_MARKERS)
    ) and value not in SEMANTIC_NODE_TERMS:
        return False
    return True


def pairwise_entity_matches(query: str) -> List[Tuple[str, str]]:
    matches: List[Tuple[str, str]] = []
    for pattern in POLICY.lexicon.regex_group("pairwise_entity_patterns"):
        for left, right in re.findall(pattern, query):
            left_text = clean_entity_phrase(left)
            right_text = clean_entity_phrase(right)
            if looks_like_entity(left_text) and looks_like_entity(right_text):
                matches.append((left_text, right_text))
    return matches


def extract_query_tokens(query: str) -> List[str]:
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
            *matched_terms(normalized, TEXTURE_EFFECT_TERMS),
            *matched_terms(normalized, FLAVOR_TERMS),
            *matched_terms(normalized, TECHNIQUE_TERMS),
            *matched_terms(normalized, HEALTH_TERMS),
            *matched_terms(normalized, CUISINE_STYLE_TERMS),
            *matched_terms(normalized, INGREDIENT_CATEGORY_TERMS),
        ]
    )

    cleaned: List[str] = []
    for token in [*raw_tokens, *matched]:
        value = clean_entity_phrase(token)
        if not value:
            continue
        if len(value) == 1 and not re.search(r"[A-Za-z0-9]", value):
            continue
        if is_stopword_like(value):
            continue
        cleaned.append(value)

    return remove_subsumed_tokens(cleaned)


def fallback_keywords(query: str) -> List[str]:
    return extract_query_tokens(query)


def fallback_entity_phrases(query: str) -> List[str]:
    normalized = normalize_query_text(query)
    if not normalized:
        return []

    phrases: List[str] = []
    for left, right in pairwise_entity_matches(normalized):
        phrases.extend([left, right])

    for marker in ENTITY_PHRASE_MARKERS:
        if marker not in normalized:
            continue
        left, right = normalized.split(marker, 1)
        left_text = clean_entity_phrase(left)
        right_text = clean_entity_phrase(right)
        if looks_like_entity(left_text):
            phrases.append(left_text)
        if marker in ENTITY_TARGET_MARKERS and looks_like_entity(right_text):
            phrases.append(right_text)

    phrases.extend(matched_terms(normalized, TEXTURE_EFFECT_TERMS))
    phrases.extend(matched_terms(normalized, FLAVOR_TERMS))
    return dedupe_preserve_order(phrases)


def extract_entity_candidates(query: str) -> List[str]:
    normalized = normalize_query_text(query)
    candidates = dedupe_preserve_order(
        [
            *fallback_entity_phrases(normalized),
            *extract_query_tokens(normalized),
            *matched_terms(normalized, TEXTURE_EFFECT_TERMS),
            *matched_terms(normalized, FLAVOR_TERMS),
        ]
    )
    filtered: List[str] = []
    for candidate in candidates:
        if candidate in GRAPH_GENERIC_TERMS:
            continue
        if candidate in STRUCTURAL_REASONING_MARKERS:
            continue
        if looks_like_entity(candidate):
            filtered.append(candidate)
    return normalize_graph_sources(filtered)


def normalize_graph_sources(values: Sequence[str]) -> List[str]:
    normalized: List[str] = []
    for value in values or []:
        text = str(value or "").strip()
        if not text:
            continue
        for prefix in GRAPH_SOURCE_PREFIXES:
            if text.startswith(prefix) and len(text) > len(prefix):
                text = text[len(prefix) :]
        for suffix in GRAPH_SOURCE_SUFFIXES:
            if text.endswith(suffix) and len(text) > len(suffix):
                text = text[: -len(suffix)]
        text = clean_entity_phrase(text)
        if not looks_like_entity(text):
            continue
        if text not in normalized:
            normalized.append(text)
    return remove_subsumed_tokens(normalized)


def infer_graph_query_type(query: str) -> str:
    normalized = normalize_query_text(query)
    if not normalized:
        return "entity_relation"
    if contains_any(normalized, PATH_MARKERS) or pairwise_entity_matches(normalized):
        return "path_finding"
    if contains_any(normalized, SUBGRAPH_MARKERS):
        return "subgraph"
    if contains_any(normalized, POLICY.lexicon.term_group("clustering_markers")):
        return "clustering"
    if contains_any(normalized, RELATION_MARKERS) or contains_any(
        normalized, STRUCTURAL_REASONING_MARKERS
    ):
        return "multi_hop"
    return "entity_relation"


def infer_relation_types(query: str) -> List[str]:
    normalized = normalize_query_text(query)
    relation_types: List[str] = []
    for relation_type, markers in RELATION_QUERY_MARKERS.items():
        if relation_type in GRAPH_RELATION_TYPES and contains_any(normalized, markers):
            relation_types.append(relation_type)
    return dedupe_preserve_order(relation_types)


def extract_minutes(query: str) -> int | None:
    for pattern in POLICY.lexicon.regex_group("time_minutes_patterns"):
        match = re.search(pattern, query)
        if match:
            return int(round(float(match.group(1))))
    for pattern in POLICY.lexicon.regex_group("time_hours_patterns"):
        match = re.search(pattern, query)
        if match:
            return int(round(float(match.group(1)) * 60))
    if contains_any(query, POLICY.lexicon.regex_group("time_half_hour_patterns")):
        return 30
    return None


def extract_style(query: str) -> str:
    for style in CUISINE_STYLE_TERMS:
        if style in query:
            return style
    return ""


def extract_difficulty(query: str) -> str:
    for difficulty in DIFFICULTY_TERMS:
        if difficulty in query:
            return difficulty
    return ""


def extract_excluded_terms(query: str) -> List[str]:
    excluded: List[str] = []
    for pattern in POLICY.lexicon.regex_group("excluded_term_patterns"):
        for match in re.findall(pattern, query):
            value = clean_entity_phrase(match)
            if looks_like_entity(value):
                excluded.append(value)
    return dedupe_preserve_order(excluded)


def infer_query_constraints(query: str) -> Dict[str, Any]:
    normalized = normalize_query_text(query)
    query_type = infer_graph_query_type(normalized)
    recommendation_intent = has_recommendation_intent(normalized)
    filtering_intent = has_filtering_intent(normalized)
    selection_intent = recommendation_intent or filtering_intent

    explicit_minutes = extract_minutes(normalized)
    excluded_terms = extract_excluded_terms(normalized)
    style = extract_style(normalized) if selection_intent else ""
    difficulty = extract_difficulty(normalized) if selection_intent else ""
    category_hits = matched_terms(normalized, INGREDIENT_CATEGORY_TERMS) if selection_intent else []
    health_hits = matched_terms(normalized, HEALTH_TERMS) if selection_intent else []

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

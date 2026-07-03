"""Heuristic constraint extraction for query understanding."""

from __future__ import annotations

import re
from typing import Any, Dict, List

from .graph_features import infer_graph_query_type
from .lexical_features import (
    _active_registry,
    clean_entity_phrase,
    has_filtering_intent,
    has_recommendation_intent,
    looks_like_entity,
    matched_terms,
)
from .registry import (
    QueryUnderstandingRegistry,
    contains_any,
    dedupe_preserve_order,
    normalize_query_text,
)


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
    "extract_difficulty",
    "extract_excluded_terms",
    "extract_minutes",
    "extract_style",
    "infer_query_constraints",
]

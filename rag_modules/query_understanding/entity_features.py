"""Entity candidate extraction for query understanding."""

from __future__ import annotations

import re
from typing import List, Sequence, Tuple

from .lexical_features import (
    _active_registry,
    clean_entity_phrase,
    extract_query_tokens,
    looks_like_entity,
    matched_terms,
    remove_subsumed_tokens,
)
from .registry import QueryUnderstandingRegistry, dedupe_preserve_order, normalize_query_text


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

    for pattern in active_registry.policy.lexicon.regex_group("entity_reference_patterns"):
        for match in re.finditer(pattern, normalized):
            entity_reference = clean_entity_phrase(match.group(1), registry=active_registry)
            if looks_like_entity(entity_reference, registry=active_registry):
                phrases.append(entity_reference)

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

    phrases.extend(matched_terms(normalized, active_registry.semantic_node_terms))
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
            *matched_terms(normalized, active_registry.semantic_node_terms),
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


__all__ = [
    "extract_entity_candidates",
    "fallback_entity_phrases",
    "normalize_graph_sources",
    "pairwise_entity_matches",
]

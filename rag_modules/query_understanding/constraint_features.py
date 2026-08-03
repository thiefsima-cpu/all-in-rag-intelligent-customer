"""Heuristic constraint extraction for query understanding."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any, Dict, List

from ..domains.contracts import DomainQueryConstraintSchema
from ..kernel.json_types import JsonObject, as_string_list, coerce_json_object
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
    constraint_schema: DomainQueryConstraintSchema | None = None,
) -> Dict[str, Any]:
    active_registry = _active_registry(registry)
    normalized = normalize_query_text(query)
    query_type = infer_graph_query_type(normalized, registry=active_registry)
    recommendation_intent = has_recommendation_intent(normalized, registry=active_registry)
    filtering_intent = has_filtering_intent(normalized, registry=active_registry)
    selection_intent = recommendation_intent or filtering_intent

    explicit_minutes = extract_minutes(normalized, registry=active_registry)
    excluded_terms = extract_excluded_terms(normalized, registry=active_registry)
    extension = _infer_domain_extension(
        normalized,
        excluded_terms=excluded_terms,
        selection_intent=selection_intent,
        registry=active_registry,
        schema=constraint_schema,
    )

    if (
        query_type in {"path_finding", "multi_hop", "subgraph", "clustering"}
        and not selection_intent
    ):
        extension = {}

    return {
        "entity_terms": [],
        "excluded_entity_terms": excluded_terms,
        "relation_types": [],
        "temporal_filters": (
            {"max_duration_minutes": explicit_minutes}
            if filtering_intent and explicit_minutes is not None
            else {}
        ),
        "structured_filters": {},
        "extension": extension,
    }


def _infer_domain_extension(
    query: str,
    *,
    excluded_terms: list[str],
    selection_intent: bool,
    registry: QueryUnderstandingRegistry,
    schema: DomainQueryConstraintSchema | None,
) -> JsonObject:
    if not selection_intent or schema is None:
        return {}
    extension: JsonObject = {}
    for field in schema.fields:
        if not field.term_group:
            continue
        matches = matched_terms(query, registry.policy.lexicon.term_group(field.term_group))
        if matches:
            extension[field.name] = matches[0] if field.first_match_only else matches
    for field_name in schema.excluded_term_fields:
        if excluded_terms:
            extension[field_name] = list(excluded_terms)
    return extension


def normalize_query_constraints(
    payload: Mapping[str, object] | None,
    *,
    schema: DomainQueryConstraintSchema | None,
) -> JsonObject:
    """Project planner output into the neutral core plus the selected pack extension."""

    data = payload or {}
    temporal = coerce_json_object(data.get("temporal_filters"))
    legacy_time = data.get("time")
    legacy_time_payload = legacy_time if isinstance(legacy_time, Mapping) else {}
    if schema and schema.maximum_duration_field:
        maximum_duration = legacy_time_payload.get(schema.maximum_duration_field)
        if maximum_duration not in (None, "") and "max_duration_minutes" not in temporal:
            temporal["max_duration_minutes"] = maximum_duration
    return {
        "entity_terms": as_string_list(data.get("entity_terms") or data.get("include_terms")),
        "excluded_entity_terms": as_string_list(
            data.get("excluded_entity_terms") or data.get("exclude_terms")
        ),
        "relation_types": as_string_list(data.get("relation_types")),
        "temporal_filters": temporal,
        "structured_filters": coerce_json_object(data.get("structured_filters")),
        "extension": schema.project_extension(data) if schema else {},
    }


__all__ = [
    "extract_excluded_terms",
    "extract_minutes",
    "infer_query_constraints",
    "normalize_query_constraints",
]

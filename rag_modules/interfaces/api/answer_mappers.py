"""Payload mapping helpers for answer API DTOs."""

from __future__ import annotations

from ...contracts import (
    QueryPlan,
    QuerySemanticProfile,
    QuerySemanticScoreBreakdown,
    RetrievalRequest,
)
from ...domain.shared.query_constraints import QueryConstraints
from ...retrieval.candidate_generator import (
    CANDIDATE_SOURCE_ERROR_CIRCUIT_OPEN,
    CANDIDATE_SOURCE_ERROR_DEGRADED,
    CANDIDATE_SOURCE_ERROR_REQUEST_SKIPPED,
    CANDIDATE_SOURCE_ERROR_RETRIEVAL_FAILED,
)
from ...runtime.json_types import JsonObject, coerce_json_object
from .error_models import ErrorCode


def constraints_payload(value: QueryConstraints) -> JsonObject:
    return {
        "include_terms": list(value.include_terms),
        "exclude_terms": list(value.exclude_terms),
        "ingredients": list(value.ingredients),
        "excluded_ingredients": list(value.excluded_ingredients),
        "cuisine_terms": list(value.cuisine_terms),
        "excluded_cuisine_terms": list(value.excluded_cuisine_terms),
        "category_terms": list(value.category_terms),
        "health_terms": list(value.health_terms),
        "preference_terms": list(value.preference_terms),
        "time": {
            "max_total_minutes": value.max_total_minutes,
            "max_prep_minutes": value.max_prep_minutes,
            "max_cook_minutes": value.max_cook_minutes,
        },
        "needs_recipe_recommendation": value.needs_recipe_recommendation,
    }


def score_breakdown_payload(value: QuerySemanticScoreBreakdown) -> JsonObject:
    return {
        "relation_hit_count": value.relation_hit_count,
        "constraint_hit_count": value.constraint_hit_count,
        "structural_hit_count": value.structural_hit_count,
        "fast_rule_hit_count": value.fast_rule_hit_count,
        "length_factor": value.length_factor,
        "lexical_relationship_intensity": value.lexical_relationship_intensity,
        "relation_hit_intensity_boost": value.relation_hit_intensity_boost,
        "lexical_complexity": value.lexical_complexity,
        "relation_hit_complexity_boost": value.relation_hit_complexity_boost,
        "relationship_intensity": value.relationship_intensity,
        "complexity": value.complexity,
    }


def semantic_profile_payload(value: QuerySemanticProfile) -> JsonObject:
    return {
        "query": value.query,
        "query_type": value.query_type,
        "source_entities": list(value.source_entities),
        "target_entities": list(value.target_entities),
        "relation_types": list(value.relation_types),
        "entity_keywords": list(value.entity_keywords),
        "topic_keywords": list(value.topic_keywords),
        "constraints": coerce_json_object(value.constraints),
        "complexity": value.complexity,
        "relationship_intensity": value.relationship_intensity,
        "reasoning_required": value.reasoning_required,
        "needs_recipe_recommendation": value.needs_recipe_recommendation,
        "recommendation_hits": list(value.recommendation_hits),
        "relation_hits": list(value.relation_hits),
        "constraint_hits": list(value.constraint_hits),
        "structural_hits": list(value.structural_hits),
        "fast_rule_hits": list(value.fast_rule_hits),
        "score_breakdown": score_breakdown_payload(value.score_breakdown),
    }


def query_plan_payload(value: QueryPlan) -> JsonObject:
    return {
        "query": value.query,
        "intent": value.intent,
        "complexity": value.complexity,
        "relationship_intensity": value.relationship_intensity,
        "reasoning_required": value.reasoning_required,
        "strategy": value.strategy_value,
        "confidence": value.confidence,
        "reasoning": value.reasoning,
        "entity_keywords": list(value.entity_keywords),
        "topic_keywords": list(value.topic_keywords),
        "graph_query_type": value.graph_query_type,
        "source_entities": list(value.source_entities),
        "target_entities": list(value.target_entities),
        "relation_types": list(value.relation_types),
        "max_depth": value.max_depth,
        "constraints": constraints_payload(value.constraints),
        "needs_recipe_recommendation": value.needs_recipe_recommendation,
        "answer_style": value.answer_style,
        "planner_version": value.planner_version,
        "used_cache": value.used_cache,
        "fallback_reason": value.fallback_reason,
        "planner_mode": value.planner_mode_value,
        "semantic_profile": semantic_profile_payload(value.semantic_profile),
        "validation_errors": list(value.validation_errors),
    }


def retrieval_request_payload(value: RetrievalRequest | None) -> JsonObject:
    if value is None:
        return {}
    return {
        "query": value.query,
        "top_k": value.top_k,
        "candidate_k": value.candidate_k,
        "strategy": value.strategy,
        "constraints": constraints_payload(value.effective_constraints),
        "query_plan": query_plan_payload(value.query_plan) if value.query_plan else None,
        "entity_keywords": list(value.entity_keywords),
        "topic_keywords": list(value.topic_keywords),
        "metadata": coerce_json_object(value.metadata),
    }


def public_answer_error(value: str) -> str:
    return ErrorCode.ANSWER_FAILED.value if str(value or "") else ""


_LEGACY_DEGRADED_CANDIDATE_ERROR_CODES = {
    "exception": CANDIDATE_SOURCE_ERROR_RETRIEVAL_FAILED,
    "circuit_open": CANDIDATE_SOURCE_ERROR_CIRCUIT_OPEN,
    "request_skip": CANDIDATE_SOURCE_ERROR_REQUEST_SKIPPED,
}


def _public_degraded_candidate(value: object) -> JsonObject:
    candidate = coerce_json_object(value)
    if not candidate:
        return {}
    error_code = str(candidate.get("error_code") or "").strip()
    if not error_code:
        reason = str(candidate.get("reason") or "").strip()
        error_code = _LEGACY_DEGRADED_CANDIDATE_ERROR_CODES.get(reason, "")
    if not error_code and str(candidate.get("circuit_state") or "").strip().lower() == "open":
        error_code = CANDIDATE_SOURCE_ERROR_CIRCUIT_OPEN
    if not error_code:
        error_code = CANDIDATE_SOURCE_ERROR_DEGRADED
    return {
        "source": str(candidate.get("source") or "").strip(),
        "error_code": error_code,
        "error_type": str(candidate.get("error_type") or "").strip(),
    }


def public_degraded_candidates(values: object) -> list[JsonObject]:
    if not isinstance(values, list):
        return []
    return [
        candidate
        for candidate in (_public_degraded_candidate(item) for item in values)
        if candidate
    ]


def public_degradation_payload(value: object) -> JsonObject:
    payload: dict[str, object] = dict(coerce_json_object(value))
    if "degraded_candidates" in payload:
        payload["degraded_candidates"] = public_degraded_candidates(
            payload.get("degraded_candidates")
        )
    return coerce_json_object(payload)


__all__ = [
    "constraints_payload",
    "public_answer_error",
    "public_degradation_payload",
    "public_degraded_candidates",
    "query_plan_payload",
    "retrieval_request_payload",
    "semantic_profile_payload",
]

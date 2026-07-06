"""Semantic scoring rules shared by routing and planning."""

from __future__ import annotations

from typing import Sequence

from ..contracts import QuerySemanticRuntimeSettings, QuerySemanticScoreBreakdown
from ..query_policy.models import QueryPolicyBundle
from .features import infer_graph_query_type
from .registry import (
    QueryUnderstandingRegistry,
    marker_hits,
    normalize_query_text,
    query_registry,
)


def _active_registry(
    *,
    policy_bundle: QueryPolicyBundle | None = None,
    registry: QueryUnderstandingRegistry | None = None,
) -> QueryUnderstandingRegistry:
    return registry or query_registry(policy_bundle)


def build_query_semantic_score_breakdown(
    query: str,
    *,
    settings: QuerySemanticRuntimeSettings,
    policy_bundle: QueryPolicyBundle | None = None,
    registry: QueryUnderstandingRegistry | None = None,
    relation_hits: Sequence[str] | None = None,
    constraint_hits: Sequence[str] | None = None,
    structural_hits: Sequence[str] | None = None,
    fast_rule_hits: Sequence[str] | None = None,
) -> QuerySemanticScoreBreakdown:
    active_registry = _active_registry(policy_bundle=policy_bundle, registry=registry)
    policy = active_registry.policy.scoring
    normalized = normalize_query_text(query)
    relation_hits = list(relation_hits or marker_hits(normalized, active_registry.relation_markers))
    constraint_hits = list(
        constraint_hits or marker_hits(normalized, active_registry.constraint_markers)
    )
    structural_hits = list(
        structural_hits or marker_hits(normalized, active_registry.structural_reasoning_markers)
    )
    fast_rule_hits = list(
        fast_rule_hits or marker_hits(normalized, active_registry.fast_rule_markers)
    )

    relation_hit_count = len(relation_hits)
    constraint_hit_count = len(constraint_hits)
    structural_hit_count = len(structural_hits)
    fast_rule_hit_count = len(fast_rule_hits)

    reference_hits = max(
        1.0,
        len(active_registry.relation_markers) * settings.relation_intensity_reference_ratio,
    )
    lexical_relationship_intensity = min(
        1.0,
        (relation_hit_count + structural_hit_count * policy.structural_relationship_factor)
        / reference_hits,
    )

    relation_hit_intensity_boost = 0.0
    relation_hit_complexity_boost = 0.0
    if relation_hit_count or structural_hit_count:
        relation_hit_intensity_boost = min(
            1.0,
            settings.relation_hit_intensity_boost_base
            + settings.relation_hit_intensity_boost_step
            * (relation_hit_count + structural_hit_count),
        )
        relation_hit_complexity_boost = min(
            1.0,
            settings.relation_hit_complexity_boost_base
            + settings.relation_hit_complexity_boost_step
            * (relation_hit_count + structural_hit_count),
        )

    length_factor = min(len(normalized) / float(settings.complexity_length_norm_chars), 1.0)
    lexical_complexity = min(
        1.0,
        (relation_hit_count * settings.complexity_relation_hit_weight)
        + (constraint_hit_count * settings.complexity_constraint_hit_weight)
        + (structural_hit_count * settings.complexity_structural_hit_weight)
        + (length_factor * settings.complexity_length_weight),
    )

    relationship_intensity = max(lexical_relationship_intensity, relation_hit_intensity_boost)
    complexity = max(lexical_complexity, relation_hit_complexity_boost)
    return QuerySemanticScoreBreakdown(
        relation_hit_count=relation_hit_count,
        constraint_hit_count=constraint_hit_count,
        structural_hit_count=structural_hit_count,
        fast_rule_hit_count=fast_rule_hit_count,
        length_factor=length_factor,
        lexical_relationship_intensity=lexical_relationship_intensity,
        relation_hit_intensity_boost=relation_hit_intensity_boost,
        lexical_complexity=lexical_complexity,
        relation_hit_complexity_boost=relation_hit_complexity_boost,
        relationship_intensity=relationship_intensity,
        complexity=complexity,
    )


def estimate_relationship_intensity(
    query: str,
    *,
    settings: QuerySemanticRuntimeSettings,
    policy_bundle: QueryPolicyBundle | None = None,
    registry: QueryUnderstandingRegistry | None = None,
    relation_hits: Sequence[str] | None = None,
) -> float:
    return build_query_semantic_score_breakdown(
        query,
        settings=settings,
        policy_bundle=policy_bundle,
        registry=registry,
        relation_hits=relation_hits,
    ).relationship_intensity


def estimate_query_complexity(
    query: str,
    *,
    settings: QuerySemanticRuntimeSettings,
    policy_bundle: QueryPolicyBundle | None = None,
    registry: QueryUnderstandingRegistry | None = None,
    relation_hits: Sequence[str] | None = None,
    constraint_hits: Sequence[str] | None = None,
    structural_hits: Sequence[str] | None = None,
) -> float:
    return build_query_semantic_score_breakdown(
        query,
        settings=settings,
        policy_bundle=policy_bundle,
        registry=registry,
        relation_hits=relation_hits,
        constraint_hits=constraint_hits,
        structural_hits=structural_hits,
    ).complexity


def should_use_fast_rule_plan(
    query: str,
    *,
    policy_bundle: QueryPolicyBundle | None = None,
    registry: QueryUnderstandingRegistry | None = None,
    fast_rule_hits: Sequence[str] | None = None,
) -> bool:
    active_registry = _active_registry(policy_bundle=policy_bundle, registry=registry)
    if not query:
        return True
    normalized = normalize_query_text(query)
    query_type = infer_graph_query_type(normalized, registry=active_registry)
    if query_type in {"path_finding", "subgraph", "clustering"}:
        return True
    if query_type == "multi_hop" and marker_hits(
        normalized,
        active_registry.structural_reasoning_markers,
    ):
        return True
    return bool(fast_rule_hits or marker_hits(normalized, active_registry.fast_rule_markers))


__all__ = [
    "build_query_semantic_score_breakdown",
    "estimate_query_complexity",
    "estimate_relationship_intensity",
    "should_use_fast_rule_plan",
]

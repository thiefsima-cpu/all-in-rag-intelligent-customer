"""Graph-oriented intent inference built on shared lexical semantics."""

from __future__ import annotations

from typing import List, Sequence, Tuple

from ..contracts import QuerySemanticProfile, QuerySemanticRuntimeSettings
from ..query_policy import get_query_policy
from .features import (
    extract_entity_candidates,
    extract_query_tokens,
    fallback_entity_phrases,
    has_recommendation_intent,
    infer_graph_query_type,
    infer_query_constraints,
    infer_relation_types,
    matched_terms,
    normalize_graph_sources,
    pairwise_entity_matches,
)
from .registry import (
    CONSTRAINT_MARKERS,
    FAST_RULE_MARKERS,
    GRAPH_GENERIC_TERMS,
    QUERY_STOPWORDS,
    RECOMMENDATION_MARKERS,
    RELATION_MARKERS,
    STRUCTURAL_REASONING_MARKERS,
    TEXTURE_EFFECT_TERMS,
    dedupe_preserve_order,
    marker_hits,
    normalize_query_text,
)
from .scoring import build_query_semantic_score_breakdown


def infer_graph_max_depth(
    query_type: str,
    relationship_intensity: float = 0.0,
    *,
    settings: QuerySemanticRuntimeSettings | None = None,
) -> int:
    settings = settings or QuerySemanticRuntimeSettings()
    graph_policy = get_query_policy().graph
    depth_map = graph_policy.max_depth
    base_key = str(query_type or "default")
    if base_key not in depth_map:
        base_key = "default"
    high_intensity_thresholds = {
        "path_finding": settings.path_finding_high_intensity_threshold,
        "subgraph": settings.subgraph_high_intensity_threshold,
        "default": settings.default_high_intensity_threshold,
    }
    high_intensity_key = f"{base_key}_high_intensity"
    if (
        high_intensity_key in depth_map
        and relationship_intensity >= high_intensity_thresholds.get(base_key, 1.0)
    ):
        return int(depth_map[high_intensity_key])
    return int(depth_map.get(base_key, depth_map["default"]))


def infer_graph_max_nodes(
    query_type: str,
    *,
    settings: QuerySemanticRuntimeSettings | None = None,
) -> int:
    _ = settings or QuerySemanticRuntimeSettings()
    graph_policy = get_query_policy().graph
    max_nodes_map = graph_policy.max_nodes
    policy_key = str(query_type or "default")
    if policy_key not in max_nodes_map:
        policy_key = "default"
    return int(max_nodes_map.get(policy_key, max_nodes_map["default"]))


def split_graph_entities(
    query: str,
    query_type: str,
    candidates: Sequence[str],
    *,
    settings: QuerySemanticRuntimeSettings | None = None,
) -> Tuple[List[str], List[str]]:
    settings = settings or QuerySemanticRuntimeSettings()
    normalized = normalize_query_text(query)
    source_entities = normalize_graph_sources(list(candidates[: settings.source_entity_limit]))
    target_entities: List[str] = []

    pair_matches = pairwise_entity_matches(normalized)
    if pair_matches and query_type in {"path_finding", "multi_hop"}:
        source_entities = normalize_graph_sources([pair_matches[0][0]])
        target_entities = normalize_graph_sources([pair_matches[0][1]])
    elif query_type == "path_finding" and len(candidates) >= 2:
        source_entities = normalize_graph_sources([candidates[0]])
        target_entities = normalize_graph_sources([candidates[1]])

    if query_type == "path_finding" and not target_entities:
        target_entities = normalize_graph_sources(matched_terms(normalized, TEXTURE_EFFECT_TERMS))

    if not source_entities and normalized:
        source_entities = [
            normalized[: settings.graph_query_fallback_name_chars].strip() or normalized
        ]

    return dedupe_preserve_order(source_entities), dedupe_preserve_order(target_entities)


def infer_query_semantic_profile(
    query: str,
    *,
    settings: QuerySemanticRuntimeSettings | None = None,
) -> QuerySemanticProfile:
    settings = settings or QuerySemanticRuntimeSettings()
    original_query = str(query or "").strip()
    normalized = normalize_query_text(original_query)

    query_type = infer_graph_query_type(normalized)
    relation_types = infer_relation_types(normalized)
    phrase_candidates = fallback_entity_phrases(normalized)
    keyword_candidates = extract_entity_candidates(normalized)
    combined_candidates = dedupe_preserve_order([*phrase_candidates, *keyword_candidates])

    source_entities, target_entities = split_graph_entities(
        normalized,
        query_type,
        combined_candidates,
        settings=settings,
    )

    entity_keyword_seed = dedupe_preserve_order(
        [
            *source_entities,
            *target_entities,
            *combined_candidates,
        ]
    )
    entity_keywords = normalize_graph_sources(
        entity_keyword_seed[: settings.semantic_profile_entity_keyword_limit]
    )

    semantic_tokens = extract_query_tokens(normalized)
    topic_pool = [
        token
        for token in semantic_tokens
        if token not in entity_keywords
        and token not in source_entities
        and token not in target_entities
        and token not in QUERY_STOPWORDS
        and token not in GRAPH_GENERIC_TERMS
        and token not in RELATION_MARKERS
        and token not in STRUCTURAL_REASONING_MARKERS
    ]
    topic_start = settings.semantic_profile_topic_keyword_start
    topic_limit = settings.semantic_profile_topic_keyword_limit
    topic_keywords = dedupe_preserve_order(
        topic_pool[topic_start : topic_start + topic_limit] or topic_pool[:topic_limit]
    )

    constraints = infer_query_constraints(normalized)
    recommendation_intent = has_recommendation_intent(normalized)
    recommendation_hits = (
        marker_hits(normalized, RECOMMENDATION_MARKERS) if recommendation_intent else []
    )
    needs_recipe_recommendation = bool(
        constraints.get("needs_recipe_recommendation") or recommendation_intent
    )
    if needs_recipe_recommendation:
        constraints["needs_recipe_recommendation"] = True

    relation_hits = marker_hits(normalized, RELATION_MARKERS)
    constraint_hits = marker_hits(normalized, CONSTRAINT_MARKERS)
    structural_hits = marker_hits(normalized, STRUCTURAL_REASONING_MARKERS)
    fast_rule_hits = marker_hits(normalized, FAST_RULE_MARKERS)

    score_breakdown = build_query_semantic_score_breakdown(
        normalized,
        settings=settings,
        relation_hits=relation_hits,
        constraint_hits=constraint_hits,
        structural_hits=structural_hits,
        fast_rule_hits=fast_rule_hits,
    )
    complexity = score_breakdown.complexity
    relationship_intensity = score_breakdown.relationship_intensity
    reasoning_required = (
        complexity >= settings.reasoning_complexity_threshold
        or relationship_intensity >= settings.reasoning_relationship_threshold
        or query_type in {"subgraph", "path_finding", "clustering", "multi_hop"}
    )

    return QuerySemanticProfile(
        query=original_query,
        query_type=query_type,
        source_entities=source_entities,
        target_entities=target_entities,
        relation_types=relation_types,
        entity_keywords=entity_keywords,
        topic_keywords=topic_keywords,
        constraints=constraints,
        complexity=complexity,
        relationship_intensity=relationship_intensity,
        reasoning_required=reasoning_required,
        needs_recipe_recommendation=needs_recipe_recommendation,
        recommendation_hits=recommendation_hits,
        relation_hits=relation_hits,
        constraint_hits=constraint_hits,
        structural_hits=structural_hits,
        fast_rule_hits=fast_rule_hits,
        score_breakdown=score_breakdown,
    )


__all__ = [
    "infer_graph_max_depth",
    "infer_graph_max_nodes",
    "infer_query_semantic_profile",
    "split_graph_entities",
]

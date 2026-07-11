"""Runtime defaults policy parser."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from ..models import (
    CandidateRuntimeDefaultsPolicy,
    CandidateSourceRuntimeDefaultsPolicy,
    PlannerRuntimeDefaultsPolicy,
    PostProcessRuntimeDefaultsPolicy,
    QuerySemanticRuntimeDefaultsPolicy,
    RuntimeDefaultsPolicy,
)
from .common import bool_field, float_field, int_field, optional_mapping, str_field, to_tuple

_SEMANTIC_FLOAT_DEFAULTS = {
    "relation_intensity_reference_ratio": 0.5,
    "complexity_relation_hit_weight": 0.14,
    "complexity_constraint_hit_weight": 0.1,
    "complexity_structural_hit_weight": 0.12,
    "complexity_length_weight": 0.28,
    "reasoning_complexity_threshold": 0.7,
    "reasoning_relationship_threshold": 0.4,
    "high_relationship_routing_threshold": 0.7,
    "relation_hit_intensity_boost_base": 0.45,
    "relation_hit_intensity_boost_step": 0.12,
    "relation_hit_complexity_boost_base": 0.55,
    "relation_hit_complexity_boost_step": 0.08,
    "multi_hop_hint_relationship_threshold": 0.55,
    "combined_strategy_relationship_threshold": 0.4,
    "combined_strategy_complexity_threshold": 0.6,
    "source_entity_seed_relationship_threshold": 0.4,
    "source_entity_backfill_relationship_threshold": 0.55,
    "rule_fallback_confidence": 0.45,
    "path_finding_high_intensity_threshold": 0.6,
    "subgraph_high_intensity_threshold": 0.5,
    "default_high_intensity_threshold": 0.7,
    "adaptive_multi_hop_subgraph_threshold": 0.7,
    "adaptive_subgraph_multi_hop_threshold": 0.45,
    "adaptive_entity_relation_multi_hop_threshold": 0.5,
}

_SEMANTIC_INT_DEFAULTS = {
    "complexity_length_norm_chars": 140,
    "source_entity_limit": 3,
    "entity_keyword_limit": 4,
    "semantic_profile_entity_keyword_limit": 6,
    "topic_keyword_limit": 4,
    "semantic_profile_topic_keyword_start": 4,
    "semantic_profile_topic_keyword_limit": 6,
    "target_entity_limit": 2,
    "multi_hop_hint_entity_count": 2,
    "entity_relation_max_depth": 1,
    "path_finding_max_depth": 3,
    "path_finding_high_intensity_max_depth": 4,
    "subgraph_max_depth": 2,
    "subgraph_high_intensity_max_depth": 3,
    "clustering_max_depth": 3,
    "default_max_depth": 2,
    "default_high_intensity_max_depth": 3,
    "entity_relation_max_nodes": 20,
    "path_finding_max_nodes": 40,
    "subgraph_max_nodes": 80,
    "clustering_max_nodes": 60,
    "default_max_nodes": 50,
    "graph_query_max_depth_cap": 4,
    "graph_query_fallback_name_chars": 16,
    "adaptive_subgraph_max_depth": 3,
    "adaptive_subgraph_max_nodes": 100,
    "adaptive_multi_hop_max_depth": 3,
    "adaptive_multi_hop_max_nodes": 50,
    "adaptive_entity_relation_max_depth": 2,
    "adaptive_entity_relation_max_nodes": 40,
}


def parse_runtime_defaults(value: object, root: Path) -> RuntimeDefaultsPolicy:
    payload = optional_mapping(value, root, "runtime_defaults")
    return RuntimeDefaultsPolicy(
        planner=_parse_planner_defaults(payload, root),
        semantics=_parse_semantic_defaults(payload, root),
        candidates=_parse_candidate_defaults(payload, root),
        candidate_sources=_parse_candidate_source_defaults(payload, root),
        postprocess=_parse_postprocess_defaults(payload, root),
    )


def _section(payload: Mapping[str, object], root: Path, name: str) -> Mapping[str, object]:
    return optional_mapping(payload.get(name), root, f"runtime_defaults.{name}")


def _parse_planner_defaults(
    payload: Mapping[str, object], root: Path
) -> PlannerRuntimeDefaultsPolicy:
    planner = _section(payload, root, "planner")
    return PlannerRuntimeDefaultsPolicy(
        model_name=str_field(planner, "model_name", "qwen3.7-plus"),
        cache_size=int_field(planner, "cache_size", 128),
        timeout_seconds=int_field(planner, "timeout_seconds", 20),
        fast_rule_planning=bool_field(planner, "fast_rule_planning", True),
        llm_temperature=float_field(planner, "llm_temperature", 0.0),
        llm_max_tokens=int_field(planner, "llm_max_tokens", 1200),
    )


def _parse_semantic_defaults(
    payload: Mapping[str, object], root: Path
) -> QuerySemanticRuntimeDefaultsPolicy:
    semantics = _section(payload, root, "semantics")
    return QuerySemanticRuntimeDefaultsPolicy(
        relation_intensity_reference_ratio=_semantic_float(
            semantics, "relation_intensity_reference_ratio"
        ),
        complexity_relation_hit_weight=_semantic_float(semantics, "complexity_relation_hit_weight"),
        complexity_constraint_hit_weight=_semantic_float(
            semantics, "complexity_constraint_hit_weight"
        ),
        complexity_structural_hit_weight=_semantic_float(
            semantics, "complexity_structural_hit_weight"
        ),
        complexity_length_weight=_semantic_float(semantics, "complexity_length_weight"),
        complexity_length_norm_chars=_semantic_int(semantics, "complexity_length_norm_chars"),
        reasoning_complexity_threshold=_semantic_float(semantics, "reasoning_complexity_threshold"),
        reasoning_relationship_threshold=_semantic_float(
            semantics, "reasoning_relationship_threshold"
        ),
        high_relationship_routing_threshold=_semantic_float(
            semantics, "high_relationship_routing_threshold"
        ),
        relation_hit_intensity_boost_base=_semantic_float(
            semantics, "relation_hit_intensity_boost_base"
        ),
        relation_hit_intensity_boost_step=_semantic_float(
            semantics, "relation_hit_intensity_boost_step"
        ),
        relation_hit_complexity_boost_base=_semantic_float(
            semantics, "relation_hit_complexity_boost_base"
        ),
        relation_hit_complexity_boost_step=_semantic_float(
            semantics, "relation_hit_complexity_boost_step"
        ),
        source_entity_limit=_semantic_int(semantics, "source_entity_limit"),
        entity_keyword_limit=_semantic_int(semantics, "entity_keyword_limit"),
        semantic_profile_entity_keyword_limit=_semantic_int(
            semantics, "semantic_profile_entity_keyword_limit"
        ),
        topic_keyword_limit=_semantic_int(semantics, "topic_keyword_limit"),
        semantic_profile_topic_keyword_start=_semantic_int(
            semantics, "semantic_profile_topic_keyword_start"
        ),
        semantic_profile_topic_keyword_limit=_semantic_int(
            semantics, "semantic_profile_topic_keyword_limit"
        ),
        target_entity_limit=_semantic_int(semantics, "target_entity_limit"),
        multi_hop_hint_entity_count=_semantic_int(semantics, "multi_hop_hint_entity_count"),
        multi_hop_hint_relationship_threshold=_semantic_float(
            semantics, "multi_hop_hint_relationship_threshold"
        ),
        combined_strategy_relationship_threshold=_semantic_float(
            semantics, "combined_strategy_relationship_threshold"
        ),
        combined_strategy_complexity_threshold=_semantic_float(
            semantics, "combined_strategy_complexity_threshold"
        ),
        source_entity_seed_relationship_threshold=_semantic_float(
            semantics, "source_entity_seed_relationship_threshold"
        ),
        source_entity_backfill_relationship_threshold=_semantic_float(
            semantics, "source_entity_backfill_relationship_threshold"
        ),
        rule_fallback_confidence=_semantic_float(semantics, "rule_fallback_confidence"),
        entity_relation_max_depth=_semantic_int(semantics, "entity_relation_max_depth"),
        path_finding_max_depth=_semantic_int(semantics, "path_finding_max_depth"),
        path_finding_high_intensity_max_depth=_semantic_int(
            semantics, "path_finding_high_intensity_max_depth"
        ),
        path_finding_high_intensity_threshold=_semantic_float(
            semantics, "path_finding_high_intensity_threshold"
        ),
        subgraph_max_depth=_semantic_int(semantics, "subgraph_max_depth"),
        subgraph_high_intensity_max_depth=_semantic_int(
            semantics, "subgraph_high_intensity_max_depth"
        ),
        subgraph_high_intensity_threshold=_semantic_float(
            semantics, "subgraph_high_intensity_threshold"
        ),
        clustering_max_depth=_semantic_int(semantics, "clustering_max_depth"),
        default_max_depth=_semantic_int(semantics, "default_max_depth"),
        default_high_intensity_max_depth=_semantic_int(
            semantics, "default_high_intensity_max_depth"
        ),
        default_high_intensity_threshold=_semantic_float(
            semantics, "default_high_intensity_threshold"
        ),
        entity_relation_max_nodes=_semantic_int(semantics, "entity_relation_max_nodes"),
        path_finding_max_nodes=_semantic_int(semantics, "path_finding_max_nodes"),
        subgraph_max_nodes=_semantic_int(semantics, "subgraph_max_nodes"),
        clustering_max_nodes=_semantic_int(semantics, "clustering_max_nodes"),
        default_max_nodes=_semantic_int(semantics, "default_max_nodes"),
        graph_query_max_depth_cap=_semantic_int(semantics, "graph_query_max_depth_cap"),
        graph_query_fallback_name_chars=_semantic_int(semantics, "graph_query_fallback_name_chars"),
        adaptive_multi_hop_subgraph_threshold=_semantic_float(
            semantics, "adaptive_multi_hop_subgraph_threshold"
        ),
        adaptive_subgraph_multi_hop_threshold=_semantic_float(
            semantics, "adaptive_subgraph_multi_hop_threshold"
        ),
        adaptive_entity_relation_multi_hop_threshold=_semantic_float(
            semantics, "adaptive_entity_relation_multi_hop_threshold"
        ),
        adaptive_subgraph_max_depth=_semantic_int(semantics, "adaptive_subgraph_max_depth"),
        adaptive_subgraph_max_nodes=_semantic_int(semantics, "adaptive_subgraph_max_nodes"),
        adaptive_multi_hop_max_depth=_semantic_int(semantics, "adaptive_multi_hop_max_depth"),
        adaptive_multi_hop_max_nodes=_semantic_int(semantics, "adaptive_multi_hop_max_nodes"),
        adaptive_entity_relation_max_depth=_semantic_int(
            semantics, "adaptive_entity_relation_max_depth"
        ),
        adaptive_entity_relation_max_nodes=_semantic_int(
            semantics, "adaptive_entity_relation_max_nodes"
        ),
    )


def _semantic_float(payload: Mapping[str, object], name: str) -> float:
    return float_field(payload, name, _SEMANTIC_FLOAT_DEFAULTS[name])


def _semantic_int(payload: Mapping[str, object], name: str) -> int:
    return int_field(payload, name, _SEMANTIC_INT_DEFAULTS[name])


def _parse_candidate_defaults(
    payload: Mapping[str, object], root: Path
) -> CandidateRuntimeDefaultsPolicy:
    candidates = _section(payload, root, "candidates")
    return CandidateRuntimeDefaultsPolicy(
        hybrid_default_multiplier=int_field(candidates, "hybrid_default_multiplier", 2),
        hybrid_default_min_candidates=int_field(candidates, "hybrid_default_min_candidates", 10),
        hybrid_constraint_multiplier=int_field(candidates, "hybrid_constraint_multiplier", 6),
        hybrid_constraint_min_candidates=int_field(
            candidates, "hybrid_constraint_min_candidates", 30
        ),
        combined_multiplier=int_field(candidates, "combined_multiplier", 6),
        combined_min_candidates=int_field(candidates, "combined_min_candidates", 30),
        graph_supplement_multiplier=int_field(candidates, "graph_supplement_multiplier", 2),
        graph_supplement_min_candidates=int_field(
            candidates, "graph_supplement_min_candidates", 10
        ),
    )


def _parse_candidate_source_defaults(
    payload: Mapping[str, object], root: Path
) -> CandidateSourceRuntimeDefaultsPolicy:
    candidate_sources = _section(payload, root, "candidate_sources")
    return CandidateSourceRuntimeDefaultsPolicy(
        failure_threshold=int_field(candidate_sources, "failure_threshold", 1),
        recovery_timeout_seconds=float_field(candidate_sources, "recovery_timeout_seconds", 30.0),
        degradation_strategy=str_field(candidate_sources, "degradation_strategy", "continue"),
    )


def _parse_postprocess_defaults(
    payload: Mapping[str, object], root: Path
) -> PostProcessRuntimeDefaultsPolicy:
    postprocess = _section(payload, root, "postprocess")
    return PostProcessRuntimeDefaultsPolicy(
        enable_rerank=bool_field(postprocess, "enable_rerank", True),
        rerank_model=str_field(postprocess, "rerank_model", "qwen3-vl-rerank"),
        rerank_base_url=str_field(postprocess, "rerank_base_url", ""),
        rerank_timeout_seconds=int_field(postprocess, "rerank_timeout_seconds", 20),
        preserve_graph_evidence=bool_field(postprocess, "preserve_graph_evidence", True),
        graph_preservation_strategies=to_tuple(
            postprocess.get("graph_preservation_strategies", ("graph_rag", "combined"))
        )
        or ("graph_rag", "combined"),
    )

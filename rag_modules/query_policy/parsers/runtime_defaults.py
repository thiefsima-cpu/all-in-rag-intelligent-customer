"""Runtime defaults policy parser."""

from __future__ import annotations

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


def parse_runtime_defaults(value: object, root: Path) -> RuntimeDefaultsPolicy:
    payload = optional_mapping(value, root, "runtime_defaults")
    planner = optional_mapping(payload.get("planner"), root, "runtime_defaults.planner")
    semantics = optional_mapping(payload.get("semantics"), root, "runtime_defaults.semantics")
    candidates = optional_mapping(payload.get("candidates"), root, "runtime_defaults.candidates")
    candidate_sources = optional_mapping(
        payload.get("candidate_sources"),
        root,
        "runtime_defaults.candidate_sources",
    )
    postprocess = optional_mapping(
        payload.get("postprocess"),
        root,
        "runtime_defaults.postprocess",
    )
    return RuntimeDefaultsPolicy(
        planner=PlannerRuntimeDefaultsPolicy(
            model_name=str_field(planner, "model_name", "qwen3.7-plus"),
            cache_size=int_field(planner, "cache_size", 128),
            timeout_seconds=int_field(planner, "timeout_seconds", 20),
            fast_rule_planning=bool_field(planner, "fast_rule_planning", True),
            llm_temperature=float_field(planner, "llm_temperature", 0.0),
            llm_max_tokens=int_field(planner, "llm_max_tokens", 1200),
        ),
        semantics=QuerySemanticRuntimeDefaultsPolicy(
            relation_intensity_reference_ratio=float_field(
                semantics, "relation_intensity_reference_ratio", 0.5
            ),
            complexity_relation_hit_weight=float_field(
                semantics, "complexity_relation_hit_weight", 0.14
            ),
            complexity_constraint_hit_weight=float_field(
                semantics, "complexity_constraint_hit_weight", 0.1
            ),
            complexity_structural_hit_weight=float_field(
                semantics, "complexity_structural_hit_weight", 0.12
            ),
            complexity_length_weight=float_field(semantics, "complexity_length_weight", 0.28),
            complexity_length_norm_chars=int_field(semantics, "complexity_length_norm_chars", 140),
            reasoning_complexity_threshold=float_field(
                semantics, "reasoning_complexity_threshold", 0.7
            ),
            reasoning_relationship_threshold=float_field(
                semantics, "reasoning_relationship_threshold", 0.4
            ),
            high_relationship_routing_threshold=float_field(
                semantics, "high_relationship_routing_threshold", 0.7
            ),
            relation_hit_intensity_boost_base=float_field(
                semantics, "relation_hit_intensity_boost_base", 0.45
            ),
            relation_hit_intensity_boost_step=float_field(
                semantics, "relation_hit_intensity_boost_step", 0.12
            ),
            relation_hit_complexity_boost_base=float_field(
                semantics, "relation_hit_complexity_boost_base", 0.55
            ),
            relation_hit_complexity_boost_step=float_field(
                semantics, "relation_hit_complexity_boost_step", 0.08
            ),
            source_entity_limit=int_field(semantics, "source_entity_limit", 3),
            entity_keyword_limit=int_field(semantics, "entity_keyword_limit", 4),
            semantic_profile_entity_keyword_limit=int_field(
                semantics, "semantic_profile_entity_keyword_limit", 6
            ),
            topic_keyword_limit=int_field(semantics, "topic_keyword_limit", 4),
            semantic_profile_topic_keyword_start=int_field(
                semantics, "semantic_profile_topic_keyword_start", 4
            ),
            semantic_profile_topic_keyword_limit=int_field(
                semantics, "semantic_profile_topic_keyword_limit", 6
            ),
            target_entity_limit=int_field(semantics, "target_entity_limit", 2),
            multi_hop_hint_entity_count=int_field(semantics, "multi_hop_hint_entity_count", 2),
            multi_hop_hint_relationship_threshold=float_field(
                semantics, "multi_hop_hint_relationship_threshold", 0.55
            ),
            combined_strategy_relationship_threshold=float_field(
                semantics, "combined_strategy_relationship_threshold", 0.4
            ),
            combined_strategy_complexity_threshold=float_field(
                semantics, "combined_strategy_complexity_threshold", 0.6
            ),
            source_entity_seed_relationship_threshold=float_field(
                semantics, "source_entity_seed_relationship_threshold", 0.4
            ),
            source_entity_backfill_relationship_threshold=float_field(
                semantics, "source_entity_backfill_relationship_threshold", 0.55
            ),
            rule_fallback_confidence=float_field(semantics, "rule_fallback_confidence", 0.45),
            entity_relation_max_depth=int_field(semantics, "entity_relation_max_depth", 1),
            path_finding_max_depth=int_field(semantics, "path_finding_max_depth", 3),
            path_finding_high_intensity_max_depth=int_field(
                semantics, "path_finding_high_intensity_max_depth", 4
            ),
            path_finding_high_intensity_threshold=float_field(
                semantics, "path_finding_high_intensity_threshold", 0.6
            ),
            subgraph_max_depth=int_field(semantics, "subgraph_max_depth", 2),
            subgraph_high_intensity_max_depth=int_field(
                semantics, "subgraph_high_intensity_max_depth", 3
            ),
            subgraph_high_intensity_threshold=float_field(
                semantics, "subgraph_high_intensity_threshold", 0.5
            ),
            clustering_max_depth=int_field(semantics, "clustering_max_depth", 3),
            default_max_depth=int_field(semantics, "default_max_depth", 2),
            default_high_intensity_max_depth=int_field(
                semantics, "default_high_intensity_max_depth", 3
            ),
            default_high_intensity_threshold=float_field(
                semantics, "default_high_intensity_threshold", 0.7
            ),
            entity_relation_max_nodes=int_field(semantics, "entity_relation_max_nodes", 20),
            path_finding_max_nodes=int_field(semantics, "path_finding_max_nodes", 40),
            subgraph_max_nodes=int_field(semantics, "subgraph_max_nodes", 80),
            clustering_max_nodes=int_field(semantics, "clustering_max_nodes", 60),
            default_max_nodes=int_field(semantics, "default_max_nodes", 50),
            graph_query_max_depth_cap=int_field(semantics, "graph_query_max_depth_cap", 4),
            graph_query_fallback_name_chars=int_field(
                semantics, "graph_query_fallback_name_chars", 16
            ),
            adaptive_multi_hop_subgraph_threshold=float_field(
                semantics, "adaptive_multi_hop_subgraph_threshold", 0.7
            ),
            adaptive_subgraph_multi_hop_threshold=float_field(
                semantics, "adaptive_subgraph_multi_hop_threshold", 0.45
            ),
            adaptive_entity_relation_multi_hop_threshold=float_field(
                semantics, "adaptive_entity_relation_multi_hop_threshold", 0.5
            ),
            adaptive_subgraph_max_depth=int_field(semantics, "adaptive_subgraph_max_depth", 3),
            adaptive_subgraph_max_nodes=int_field(semantics, "adaptive_subgraph_max_nodes", 100),
            adaptive_multi_hop_max_depth=int_field(semantics, "adaptive_multi_hop_max_depth", 3),
            adaptive_multi_hop_max_nodes=int_field(semantics, "adaptive_multi_hop_max_nodes", 50),
            adaptive_entity_relation_max_depth=int_field(
                semantics, "adaptive_entity_relation_max_depth", 2
            ),
            adaptive_entity_relation_max_nodes=int_field(
                semantics, "adaptive_entity_relation_max_nodes", 40
            ),
        ),
        candidates=CandidateRuntimeDefaultsPolicy(
            hybrid_default_multiplier=int_field(candidates, "hybrid_default_multiplier", 2),
            hybrid_default_min_candidates=int_field(
                candidates, "hybrid_default_min_candidates", 10
            ),
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
        ),
        candidate_sources=CandidateSourceRuntimeDefaultsPolicy(
            failure_threshold=int_field(candidate_sources, "failure_threshold", 1),
            recovery_timeout_seconds=float_field(
                candidate_sources, "recovery_timeout_seconds", 30.0
            ),
            degradation_strategy=str_field(candidate_sources, "degradation_strategy", "continue"),
        ),
        postprocess=PostProcessRuntimeDefaultsPolicy(
            enable_rerank=bool_field(postprocess, "enable_rerank", True),
            rerank_model=str_field(postprocess, "rerank_model", "qwen3-vl-rerank"),
            rerank_base_url=str_field(postprocess, "rerank_base_url", ""),
            rerank_timeout_seconds=int_field(postprocess, "rerank_timeout_seconds", 20),
            preserve_graph_evidence=bool_field(postprocess, "preserve_graph_evidence", True),
            graph_preservation_strategies=to_tuple(
                postprocess.get("graph_preservation_strategies", ("graph_rag", "combined"))
            )
            or ("graph_rag", "combined"),
        ),
    )

"""Configuration assembly helpers."""

from __future__ import annotations

from typing import Any, Dict, Mapping

from pydantic import ValidationError

from ..query_policy.models import QueryPolicyBundle
from .models import GraphRAGConfig, default_domain_payload
from .validation import raise_validation_error


def _merge_nested_mapping(target: Dict[str, Any], updates: Mapping[str, Any]) -> None:
    for key, value in updates.items():
        key_text = str(key)
        current = target.get(key_text)
        if isinstance(current, dict) and isinstance(value, Mapping):
            _merge_nested_mapping(current, value)
        else:
            target[key_text] = dict(value) if isinstance(value, Mapping) else value


def apply_overrides(domain_payload: Dict[str, Any], overrides: Mapping[str, Any]) -> None:
    _merge_nested_mapping(domain_payload, overrides)


def query_policy_default_overlay(bundle: QueryPolicyBundle) -> dict[str, object]:
    runtime = bundle.runtime_defaults
    planner = runtime.planner
    semantics = runtime.semantics
    candidates = runtime.candidates
    candidate_sources = runtime.candidate_sources
    postprocess = runtime.postprocess
    return {
        "query_understanding": {
            "planner": {
                "cache_size": planner.cache_size,
                "fast_rule_planning": planner.fast_rule_planning,
                "llm_temperature": planner.llm_temperature,
                "llm_max_tokens": planner.llm_max_tokens,
            },
            "semantics": semantics.to_config_dict(),
        },
        "models": {
            "llm_model": planner.model_name,
            "llm_timeout_seconds": planner.timeout_seconds,
        },
        "retrieval": {
            "hybrid_default_candidate_multiplier": candidates.hybrid_default_multiplier,
            "hybrid_default_candidate_min_candidates": candidates.hybrid_default_min_candidates,
            "hybrid_constraint_candidate_multiplier": candidates.hybrid_constraint_multiplier,
            "hybrid_constraint_candidate_min_candidates": candidates.hybrid_constraint_min_candidates,
            "router_combined_candidate_multiplier": candidates.combined_multiplier,
            "router_combined_candidate_min_candidates": candidates.combined_min_candidates,
            "router_graph_supplement_candidate_multiplier": candidates.graph_supplement_multiplier,
            "router_graph_supplement_candidate_min_candidates": candidates.graph_supplement_min_candidates,
            "candidate_source_failure_threshold": candidate_sources.failure_threshold,
            "candidate_source_recovery_seconds": candidate_sources.recovery_timeout_seconds,
            "candidate_source_degradation_strategy": candidate_sources.degradation_strategy,
            "retrieval_preserve_graph_evidence": postprocess.preserve_graph_evidence,
            "retrieval_graph_preservation_strategies": list(
                postprocess.graph_preservation_strategies
            ),
        },
        "graph": {
            "entity_linker_query_type_label_priorities": {
                key: list(values)
                for key, values in bundle.relations.entity_linker_query_type_priorities.items()
            },
            "entity_linker_relation_label_priorities": {
                key: list(values)
                for key, values in bundle.relations.entity_linker_relation_priorities.items()
            },
        },
    }


def policy_resolved_domain_payload(bundle: QueryPolicyBundle) -> dict[str, dict[str, Any]]:
    payload = default_domain_payload()
    apply_overrides(payload, query_policy_default_overlay(bundle))
    return payload


def build_config_from_resolved_overrides(
    overrides: Mapping[str, Any],
    *,
    bundle: QueryPolicyBundle,
    source_kind: str,
    source: str,
) -> GraphRAGConfig:
    domain_payload = policy_resolved_domain_payload(bundle)
    apply_overrides(domain_payload, overrides)
    return build_config_from_domain_dict(
        domain_payload,
        source_kind=source_kind,
        source=source,
    )


def build_config_from_domain_dict(
    domain_payload: Mapping[str, Any],
    *,
    source_kind: str = "configuration",
    source: str = "",
) -> GraphRAGConfig:
    try:
        return GraphRAGConfig.model_validate(dict(domain_payload))
    except ValidationError as exc:
        raise_validation_error(exc, source_kind=source_kind, source=source)
        raise AssertionError("unreachable") from exc


__all__ = [
    "apply_overrides",
    "build_config_from_domain_dict",
    "build_config_from_resolved_overrides",
    "policy_resolved_domain_payload",
    "query_policy_default_overlay",
]

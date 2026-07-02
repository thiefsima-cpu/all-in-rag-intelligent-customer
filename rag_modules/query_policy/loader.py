"""Load versioned query policy bundles."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from functools import lru_cache
from pathlib import Path
from string import Formatter
from typing import cast

from .models import (
    CandidateRuntimeDefaultsPolicy,
    CandidateSourceRuntimeDefaultsPolicy,
    GenerationAnswerTypePolicy,
    GenerationDecisionPolicy,
    GenerationDecisionReasonsPolicy,
    GenerationPolicy,
    GenerationRulePlanPolicy,
    GraphPolicy,
    GraphReasoningPolicy,
    GraphSubQuestionCondition,
    GraphSubQuestionPolicy,
    LexiconPolicy,
    PlannerRuntimeDefaultsPolicy,
    PolicyLoadError,
    PolicyMetadata,
    PostProcessRuntimeDefaultsPolicy,
    PromptTemplates,
    QueryPolicyBundle,
    QuerySemanticRuntimeDefaultsPolicy,
    RelationPolicy,
    RoutingPolicy,
    RuntimeDefaultsPolicy,
    ScoringPolicy,
    SemanticRelationKeySpec,
)

SUPPORTED_SCHEMA_VERSION = "policy-bundle-v1"
DEFAULT_BUNDLE_NAME = "c9-default-v1"

_REQUIRED_PROMPT_VARIABLES = {
    "query_planner": {
        "query",
        "graph_query_types_text",
        "relation_types_text",
        "preferred_relation_types_text",
    },
    "answer_plan": {"question", "evidence_summary"},
    "answer_compose": {"question", "plan_json", "evidence_text"},
    "answer_direct": {"question", "evidence_text"},
}

_GRAPH_SUB_QUESTION_CONDITION_KEYS = {
    "entities_present",
    "relation_types_any",
    "constraints_present",
    "relationship_intensity_at_least",
    "query_markers_any",
    "fallback",
}


def default_policy_bundle_path() -> Path:
    return Path(__file__).parent / "resources" / DEFAULT_BUNDLE_NAME


def _mapping(value: object, root: Path, field_path: str) -> Mapping[str, object]:
    if not isinstance(value, dict):
        raise PolicyLoadError(
            f"Policy field must be an object: {field_path}",
            bundle_path=str(root),
            field_path=field_path,
        )
    return cast(Mapping[str, object], value)


def _optional_mapping(value: object, root: Path, field_path: str) -> Mapping[str, object]:
    if value is None:
        return {}
    return _mapping(value, root, field_path)


def _to_tuple(value: object) -> tuple[str, ...]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return tuple(str(item) for item in value if str(item).strip())
    if value is None:
        return ()
    text = str(value).strip()
    return (text,) if text else ()


def _to_tuple_map(value: object, root: Path, field_path: str) -> dict[str, tuple[str, ...]]:
    payload = _optional_mapping(value, root, field_path)
    return {str(key): _to_tuple(items) for key, items in payload.items()}


def _to_str_map(value: object, root: Path, field_path: str) -> dict[str, str]:
    payload = _optional_mapping(value, root, field_path)
    return {
        str(key): str(item)
        for key, item in payload.items()
        if str(key).strip() and str(item).strip()
    }


def _to_float_map(value: object, root: Path, field_path: str) -> dict[str, float]:
    result: dict[str, float] = {}
    for key, item in _optional_mapping(value, root, field_path).items():
        try:
            result[str(key)] = float(cast(float | int | str | bool, item))
        except (TypeError, ValueError) as exc:
            raise PolicyLoadError(
                f"Invalid float value for {key}",
                bundle_path=str(root),
                field_path=f"{field_path}.{key}",
            ) from exc
    return result


def _to_int_map(value: object, root: Path, field_path: str) -> dict[str, int]:
    result: dict[str, int] = {}
    for key, item in _optional_mapping(value, root, field_path).items():
        try:
            result[str(key)] = int(cast(float | int | str | bool, item))
        except (TypeError, ValueError) as exc:
            raise PolicyLoadError(
                f"Invalid integer value for {key}",
                bundle_path=str(root),
                field_path=f"{field_path}.{key}",
            ) from exc
    return result


def _required_str_tuple(value: object, root: Path, field_path: str) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise PolicyLoadError(
            f"Policy field must be a list: {field_path}",
            bundle_path=str(root),
            field_path=field_path,
        )
    return _to_tuple(value)


def _str_field(payload: Mapping[str, object], key: str, default: str = "") -> str:
    value = payload.get(key, default)
    return str(value if value is not None else default)


def _int_field(payload: Mapping[str, object], key: str, default: int) -> int:
    value = payload.get(key, default)
    try:
        return int(cast(float | int | str | bool, value))
    except (TypeError, ValueError):
        return default


def _float_field(payload: Mapping[str, object], key: str, default: float) -> float:
    value = payload.get(key, default)
    try:
        return float(cast(float | int | str | bool, value))
    except (TypeError, ValueError):
        return default


def _bool_field(payload: Mapping[str, object], key: str, default: bool) -> bool:
    value = payload.get(key, default)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "on"}:
            return True
        if normalized in {"false", "0", "no", "off"}:
            return False
    if isinstance(value, (int, float)):
        return bool(value)
    return default


def _to_sub_question_condition(
    value: object,
    root: Path,
    field_path: str,
) -> GraphSubQuestionCondition:
    payload = _optional_mapping(value, root, field_path)
    unknown_keys = sorted(set(payload) - _GRAPH_SUB_QUESTION_CONDITION_KEYS)
    if unknown_keys:
        unknown_key = unknown_keys[0]
        raise PolicyLoadError(
            f"Unknown graph sub-question condition: {unknown_key}",
            bundle_path=str(root),
            field_path=f"{field_path}.{unknown_key}",
        )
    constraints_rule = payload.get("constraints_present")
    constraints_any = bool(constraints_rule) if isinstance(constraints_rule, bool) else False
    constraint_fields = () if isinstance(constraints_rule, bool) else _to_tuple(constraints_rule)
    return GraphSubQuestionCondition(
        fallback=bool(payload.get("fallback", False)),
        entities_present=(
            bool(payload["entities_present"]) if "entities_present" in payload else None
        ),
        relation_types_any=_to_tuple(payload.get("relation_types_any")),
        constraints_present=constraint_fields,
        constraints_present_any=constraints_any,
        relationship_intensity_at_least=(
            float(cast(float | int | str | bool, payload["relationship_intensity_at_least"]))
            if payload.get("relationship_intensity_at_least") is not None
            else None
        ),
        query_markers_any=_to_tuple(payload.get("query_markers_any")),
    )


def _to_sub_question_items(value: object, root: Path) -> tuple[GraphSubQuestionPolicy, ...]:
    if not isinstance(value, (list, tuple)):
        raise PolicyLoadError(
            "Policy graph.sub_questions must be a list",
            bundle_path=str(root),
            field_path="graph.sub_questions",
        )
    result: list[GraphSubQuestionPolicy] = []
    for index, item in enumerate(value):
        field_path = f"graph.sub_questions[{index}]"
        payload = _mapping(item, root, field_path)
        sub_question_id = str(payload.get("id", "")).strip()
        template = str(payload.get("template", "")).strip()
        if not sub_question_id:
            raise PolicyLoadError(
                "Graph sub-question is missing id",
                bundle_path=str(root),
                field_path=f"{field_path}.id",
            )
        if not template:
            raise PolicyLoadError(
                "Graph sub-question is missing template",
                bundle_path=str(root),
                field_path=f"{field_path}.template",
            )
        result.append(
            GraphSubQuestionPolicy(
                id=sub_question_id,
                template=template,
                when=_to_sub_question_condition(payload.get("when"), root, f"{field_path}.when"),
            )
        )
    return tuple(result)


def _to_generation_answer_types(
    value: object,
    root: Path,
    field_path: str,
) -> dict[str, GenerationAnswerTypePolicy]:
    payload = _mapping(value, root, field_path)
    result: dict[str, GenerationAnswerTypePolicy] = {}
    for answer_type, raw_config in payload.items():
        config_path = f"{field_path}.{answer_type}"
        config = _mapping(raw_config, root, config_path)
        result[str(answer_type)] = GenerationAnswerTypePolicy(
            markers=_to_tuple(config.get("markers"))
        )
    return result


def _to_generation_rule_plan(
    value: Mapping[str, object],
    root: Path,
) -> GenerationRulePlanPolicy:
    _require_keys(value, _GENERATION_RULE_PLAN_KEYS, root, "generation.rule_plan")
    return GenerationRulePlanPolicy(
        default_outline=_required_str_tuple(
            value.get("default_outline"), root, "generation.rule_plan.default_outline"
        ),
        fallback_outline=_required_str_tuple(
            value.get("fallback_outline"), root, "generation.rule_plan.fallback_outline"
        ),
        graph_caution=str(value.get("graph_caution") or ""),
        missing_relation_evidence=str(value.get("missing_relation_evidence") or ""),
        sparse_evidence=str(value.get("sparse_evidence") or ""),
        missing_information_caution=str(value.get("missing_information_caution") or ""),
        fallback_claim_template=str(value.get("fallback_claim_template") or ""),
    )


def _to_generation_decision(
    value: Mapping[str, object],
    root: Path,
) -> GenerationDecisionPolicy:
    _require_keys(value, _GENERATION_DECISION_KEYS, root, "generation.decision")
    reasons = _required_mapping(value, "reasons", root, field_path="generation.decision.reasons")
    _require_keys(
        reasons,
        _GENERATION_DECISION_REASON_KEYS,
        root,
        "generation.decision.reasons",
    )
    return GenerationDecisionPolicy(
        default_answer_type=str(value.get("default_answer_type") or "direct_answer"),
        high_pressure_margin=_float_field(value, "high_pressure_margin", 0.12),
        reasons=GenerationDecisionReasonsPolicy(
            two_stage_disabled=str(reasons.get("two_stage_disabled") or ""),
            no_route_analysis=str(reasons.get("no_route_analysis") or ""),
            graph_without_analysis=str(reasons.get("graph_without_analysis") or ""),
            graph_rag=str(reasons.get("graph_rag") or ""),
            combined_pressure=str(reasons.get("combined_pressure") or ""),
            high_pressure=str(reasons.get("high_pressure") or ""),
            simple=str(reasons.get("simple") or ""),
        ),
    )


def _to_runtime_defaults(value: object, root: Path) -> RuntimeDefaultsPolicy:
    payload = _optional_mapping(value, root, "runtime_defaults")
    planner = _optional_mapping(payload.get("planner"), root, "runtime_defaults.planner")
    semantics = _optional_mapping(payload.get("semantics"), root, "runtime_defaults.semantics")
    candidates = _optional_mapping(payload.get("candidates"), root, "runtime_defaults.candidates")
    candidate_sources = _optional_mapping(
        payload.get("candidate_sources"),
        root,
        "runtime_defaults.candidate_sources",
    )
    postprocess = _optional_mapping(
        payload.get("postprocess"),
        root,
        "runtime_defaults.postprocess",
    )
    return RuntimeDefaultsPolicy(
        planner=PlannerRuntimeDefaultsPolicy(
            model_name=_str_field(planner, "model_name", "qwen3.7-plus"),
            cache_size=_int_field(planner, "cache_size", 128),
            timeout_seconds=_int_field(planner, "timeout_seconds", 20),
            fast_rule_planning=_bool_field(planner, "fast_rule_planning", True),
            llm_temperature=_float_field(planner, "llm_temperature", 0.0),
            llm_max_tokens=_int_field(planner, "llm_max_tokens", 1200),
        ),
        semantics=QuerySemanticRuntimeDefaultsPolicy(
            relation_intensity_reference_ratio=_float_field(
                semantics, "relation_intensity_reference_ratio", 0.5
            ),
            complexity_relation_hit_weight=_float_field(
                semantics, "complexity_relation_hit_weight", 0.14
            ),
            complexity_constraint_hit_weight=_float_field(
                semantics, "complexity_constraint_hit_weight", 0.1
            ),
            complexity_structural_hit_weight=_float_field(
                semantics, "complexity_structural_hit_weight", 0.12
            ),
            complexity_length_weight=_float_field(semantics, "complexity_length_weight", 0.28),
            complexity_length_norm_chars=_int_field(semantics, "complexity_length_norm_chars", 140),
            reasoning_complexity_threshold=_float_field(
                semantics, "reasoning_complexity_threshold", 0.7
            ),
            reasoning_relationship_threshold=_float_field(
                semantics, "reasoning_relationship_threshold", 0.4
            ),
            high_relationship_routing_threshold=_float_field(
                semantics, "high_relationship_routing_threshold", 0.7
            ),
            relation_hit_intensity_boost_base=_float_field(
                semantics, "relation_hit_intensity_boost_base", 0.45
            ),
            relation_hit_intensity_boost_step=_float_field(
                semantics, "relation_hit_intensity_boost_step", 0.12
            ),
            relation_hit_complexity_boost_base=_float_field(
                semantics, "relation_hit_complexity_boost_base", 0.55
            ),
            relation_hit_complexity_boost_step=_float_field(
                semantics, "relation_hit_complexity_boost_step", 0.08
            ),
            source_entity_limit=_int_field(semantics, "source_entity_limit", 3),
            entity_keyword_limit=_int_field(semantics, "entity_keyword_limit", 4),
            semantic_profile_entity_keyword_limit=_int_field(
                semantics, "semantic_profile_entity_keyword_limit", 6
            ),
            topic_keyword_limit=_int_field(semantics, "topic_keyword_limit", 4),
            semantic_profile_topic_keyword_start=_int_field(
                semantics, "semantic_profile_topic_keyword_start", 4
            ),
            semantic_profile_topic_keyword_limit=_int_field(
                semantics, "semantic_profile_topic_keyword_limit", 6
            ),
            target_entity_limit=_int_field(semantics, "target_entity_limit", 2),
            multi_hop_hint_entity_count=_int_field(semantics, "multi_hop_hint_entity_count", 2),
            multi_hop_hint_relationship_threshold=_float_field(
                semantics, "multi_hop_hint_relationship_threshold", 0.55
            ),
            combined_strategy_relationship_threshold=_float_field(
                semantics, "combined_strategy_relationship_threshold", 0.4
            ),
            combined_strategy_complexity_threshold=_float_field(
                semantics, "combined_strategy_complexity_threshold", 0.6
            ),
            source_entity_seed_relationship_threshold=_float_field(
                semantics, "source_entity_seed_relationship_threshold", 0.4
            ),
            source_entity_backfill_relationship_threshold=_float_field(
                semantics, "source_entity_backfill_relationship_threshold", 0.55
            ),
            rule_fallback_confidence=_float_field(semantics, "rule_fallback_confidence", 0.45),
            entity_relation_max_depth=_int_field(semantics, "entity_relation_max_depth", 1),
            path_finding_max_depth=_int_field(semantics, "path_finding_max_depth", 3),
            path_finding_high_intensity_max_depth=_int_field(
                semantics, "path_finding_high_intensity_max_depth", 4
            ),
            path_finding_high_intensity_threshold=_float_field(
                semantics, "path_finding_high_intensity_threshold", 0.6
            ),
            subgraph_max_depth=_int_field(semantics, "subgraph_max_depth", 2),
            subgraph_high_intensity_max_depth=_int_field(
                semantics, "subgraph_high_intensity_max_depth", 3
            ),
            subgraph_high_intensity_threshold=_float_field(
                semantics, "subgraph_high_intensity_threshold", 0.5
            ),
            clustering_max_depth=_int_field(semantics, "clustering_max_depth", 3),
            default_max_depth=_int_field(semantics, "default_max_depth", 2),
            default_high_intensity_max_depth=_int_field(
                semantics, "default_high_intensity_max_depth", 3
            ),
            default_high_intensity_threshold=_float_field(
                semantics, "default_high_intensity_threshold", 0.7
            ),
            entity_relation_max_nodes=_int_field(semantics, "entity_relation_max_nodes", 20),
            path_finding_max_nodes=_int_field(semantics, "path_finding_max_nodes", 40),
            subgraph_max_nodes=_int_field(semantics, "subgraph_max_nodes", 80),
            clustering_max_nodes=_int_field(semantics, "clustering_max_nodes", 60),
            default_max_nodes=_int_field(semantics, "default_max_nodes", 50),
            graph_query_max_depth_cap=_int_field(semantics, "graph_query_max_depth_cap", 4),
            graph_query_fallback_name_chars=_int_field(
                semantics, "graph_query_fallback_name_chars", 16
            ),
            adaptive_multi_hop_subgraph_threshold=_float_field(
                semantics, "adaptive_multi_hop_subgraph_threshold", 0.7
            ),
            adaptive_subgraph_multi_hop_threshold=_float_field(
                semantics, "adaptive_subgraph_multi_hop_threshold", 0.45
            ),
            adaptive_entity_relation_multi_hop_threshold=_float_field(
                semantics, "adaptive_entity_relation_multi_hop_threshold", 0.5
            ),
            adaptive_subgraph_max_depth=_int_field(semantics, "adaptive_subgraph_max_depth", 3),
            adaptive_subgraph_max_nodes=_int_field(semantics, "adaptive_subgraph_max_nodes", 100),
            adaptive_multi_hop_max_depth=_int_field(semantics, "adaptive_multi_hop_max_depth", 3),
            adaptive_multi_hop_max_nodes=_int_field(semantics, "adaptive_multi_hop_max_nodes", 50),
            adaptive_entity_relation_max_depth=_int_field(
                semantics, "adaptive_entity_relation_max_depth", 2
            ),
            adaptive_entity_relation_max_nodes=_int_field(
                semantics, "adaptive_entity_relation_max_nodes", 40
            ),
        ),
        candidates=CandidateRuntimeDefaultsPolicy(
            hybrid_default_multiplier=_int_field(candidates, "hybrid_default_multiplier", 2),
            hybrid_default_min_candidates=_int_field(
                candidates, "hybrid_default_min_candidates", 10
            ),
            hybrid_constraint_multiplier=_int_field(candidates, "hybrid_constraint_multiplier", 6),
            hybrid_constraint_min_candidates=_int_field(
                candidates, "hybrid_constraint_min_candidates", 30
            ),
            combined_multiplier=_int_field(candidates, "combined_multiplier", 6),
            combined_min_candidates=_int_field(candidates, "combined_min_candidates", 30),
            graph_supplement_multiplier=_int_field(candidates, "graph_supplement_multiplier", 2),
            graph_supplement_min_candidates=_int_field(
                candidates, "graph_supplement_min_candidates", 10
            ),
        ),
        candidate_sources=CandidateSourceRuntimeDefaultsPolicy(
            failure_threshold=_int_field(candidate_sources, "failure_threshold", 1),
            recovery_timeout_seconds=_float_field(
                candidate_sources, "recovery_timeout_seconds", 30.0
            ),
            degradation_strategy=_str_field(candidate_sources, "degradation_strategy", "continue"),
        ),
        postprocess=PostProcessRuntimeDefaultsPolicy(
            enable_rerank=_bool_field(postprocess, "enable_rerank", True),
            rerank_model=_str_field(postprocess, "rerank_model", "qwen3-vl-rerank"),
            rerank_base_url=_str_field(postprocess, "rerank_base_url", ""),
            rerank_timeout_seconds=_int_field(postprocess, "rerank_timeout_seconds", 20),
            preserve_graph_evidence=_bool_field(postprocess, "preserve_graph_evidence", True),
            graph_preservation_strategies=_to_tuple(
                postprocess.get("graph_preservation_strategies", ("graph_rag", "combined"))
            )
            or ("graph_rag", "combined"),
        ),
    )


def _read_json(path: Path, root: Path) -> dict[str, object]:
    try:
        with path.open("r", encoding="utf-8") as file:
            payload: object = json.load(file)
    except (OSError, json.JSONDecodeError) as exc:
        raise PolicyLoadError(
            f"Unable to read JSON file: {path.name}",
            bundle_path=str(root),
        ) from exc
    if not isinstance(payload, dict):
        raise PolicyLoadError(
            f"JSON file must contain an object: {path.name}",
            bundle_path=str(root),
        )
    raw_items = cast(Mapping[object, object], payload)
    return {str(key): value for key, value in raw_items.items()}


def _hash_payload(payload: Mapping[str, object]) -> str:
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _hash_texts(texts: Mapping[str, str]) -> str:
    canonical = json.dumps(
        {name: texts[name] for name in sorted(texts)},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _required_mapping(
    payload: Mapping[str, object],
    key: str,
    root: Path,
    *,
    field_path: str | None = None,
) -> Mapping[str, object]:
    path = field_path or key
    value = payload.get(key)
    if not isinstance(value, dict):
        raise PolicyLoadError(
            f"Policy section must be an object: {path}",
            bundle_path=str(root),
            field_path=path,
        )
    return cast(Mapping[str, object], value)


def _require_keys(
    payload: Mapping[str, object], keys: tuple[str, ...], root: Path, field_path: str
) -> None:
    for key in keys:
        if key not in payload:
            raise PolicyLoadError(
                f"Policy field is required: {field_path}.{key}",
                bundle_path=str(root),
                field_path=f"{field_path}.{key}",
            )


_GENERATION_RULE_PLAN_KEYS = (
    "default_outline",
    "fallback_outline",
    "graph_caution",
    "missing_relation_evidence",
    "sparse_evidence",
    "missing_information_caution",
    "fallback_claim_template",
)

_GENERATION_DECISION_KEYS = ("default_answer_type", "high_pressure_margin", "reasons")

_GENERATION_DECISION_REASON_KEYS = (
    "two_stage_disabled",
    "no_route_analysis",
    "graph_without_analysis",
    "graph_rag",
    "combined_pressure",
    "high_pressure",
    "simple",
)

_GENERATION_FALLBACK_ANSWER_KEYS = (
    "empty_evidence",
    "heading",
    "item_line",
    "matched_terms",
    "graph_claim",
    "text_claim",
    "constraint_reasons",
    "boundary",
    "model_unavailable",
)

_GRAPH_REASONING_KEYS = (
    "causal_relation_types",
    "compositional_relation_types",
    "comparison_markers",
    "semantic_relation_key_specs",
)


def _verify_manifest(manifest: Mapping[str, object], root: Path) -> None:
    schema_version = manifest.get("schema_version")
    if schema_version != SUPPORTED_SCHEMA_VERSION:
        raise PolicyLoadError(
            f"Unsupported or missing schema_version: {schema_version!r}",
            bundle_path=str(root),
            field_path="schema_version",
        )
    for field_name in ("policy_version", "prompt_version", "name", "policy_path", "prompts"):
        if field_name not in manifest:
            raise PolicyLoadError(
                f"Missing manifest field: {field_name}",
                bundle_path=str(root),
                field_path=field_name,
            )


def _prompt_variables(template: str) -> set[str]:
    variables: set[str] = set()
    for _, field_name, _, _ in Formatter().parse(template):
        if field_name:
            variables.add(field_name.split(".", 1)[0].split("[", 1)[0])
    return variables


def _verify_prompt_variables(texts: Mapping[str, str], root: Path) -> None:
    for prompt_name, required_variables in _REQUIRED_PROMPT_VARIABLES.items():
        if prompt_name not in texts:
            raise PolicyLoadError(
                f"Missing prompt template: {prompt_name}",
                bundle_path=str(root),
                field_path=f"prompts.{prompt_name}",
            )
        actual_variables = _prompt_variables(texts[prompt_name])
        missing = sorted(required_variables - actual_variables)
        if missing:
            raise PolicyLoadError(
                f"Prompt {prompt_name} is missing variable: {missing[0]}",
                bundle_path=str(root),
                field_path=f"prompts.{prompt_name}.{missing[0]}",
            )


def _read_prompts(manifest: Mapping[str, object], root: Path) -> dict[str, str]:
    prompts = _mapping(manifest.get("prompts"), root, "prompts")
    texts: dict[str, str] = {}
    for prompt_name in _REQUIRED_PROMPT_VARIABLES:
        relative_path = prompts.get(prompt_name)
        if not relative_path:
            raise PolicyLoadError(
                f"Missing prompt path: {prompt_name}",
                bundle_path=str(root),
                field_path=f"prompts.{prompt_name}",
            )
        path = root / str(relative_path)
        try:
            texts[prompt_name] = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise PolicyLoadError(
                f"Unable to read prompt file: {relative_path}",
                bundle_path=str(root),
                field_path=f"prompts.{prompt_name}",
            ) from exc
    _verify_prompt_variables(texts, root)
    return texts


def _verify_relation_references(
    relation_types: tuple[str, ...],
    preferred_relation_excluded_types: tuple[str, ...],
    relation_index_keywords: Mapping[str, tuple[str, ...]],
    relation_index_suffix_templates: Mapping[str, str],
    relation_query_markers: Mapping[str, tuple[str, ...]],
    graph_reasoning: GraphReasoningPolicy,
    root: Path,
) -> None:
    known = set(relation_types)
    for field_name, relation_map in (
        ("relations.preferred_relation_excluded_types", preferred_relation_excluded_types),
        ("relations.relation_index_keywords", relation_index_keywords),
        ("relations.relation_index_suffix_templates", relation_index_suffix_templates),
        ("relations.relation_query_markers", relation_query_markers),
        ("graph.reasoning.causal_relation_types", graph_reasoning.causal_relation_types),
        (
            "graph.reasoning.compositional_relation_types",
            graph_reasoning.compositional_relation_types,
        ),
        (
            "graph.reasoning.semantic_relation_key_specs",
            tuple(graph_reasoning.semantic_relation_key_specs),
        ),
    ):
        unknown = sorted(set(relation_map) - known)
        if unknown:
            raise PolicyLoadError(
                f"Unknown graph relation type: {unknown[0]}",
                bundle_path=str(root),
                field_path=f"{field_name}.{unknown[0]}",
            )


def _to_semantic_relation_key_specs(
    value: object,
    root: Path,
) -> dict[str, SemanticRelationKeySpec]:
    field_path = "graph.reasoning.semantic_relation_key_specs"
    payload = _mapping(value, root, field_path)

    specs: dict[str, SemanticRelationKeySpec] = {}
    for relation_type, raw_spec in payload.items():
        relation_name = str(relation_type).strip()
        spec_path = f"{field_path}.{relation_name}"
        if not relation_name:
            raise PolicyLoadError(
                "Semantic relation key spec has empty relation type",
                bundle_path=str(root),
                field_path=field_path,
            )
        spec = _mapping(raw_spec, root, spec_path)
        _require_keys(spec, ("target_field", "key_fields"), root, spec_path)
        target_field = str(spec.get("target_field") or "").strip()
        if not target_field:
            raise PolicyLoadError(
                "Semantic relation key spec target_field is required",
                bundle_path=str(root),
                field_path=f"{spec_path}.target_field",
            )
        key_fields = _required_str_tuple(spec.get("key_fields"), root, f"{spec_path}.key_fields")
        if not key_fields:
            raise PolicyLoadError(
                "Semantic relation key spec key_fields cannot be empty",
                bundle_path=str(root),
                field_path=f"{spec_path}.key_fields",
            )
        specs[relation_name] = SemanticRelationKeySpec(
            target_field=target_field,
            key_fields=key_fields,
        )
    return specs


def _to_graph_reasoning_policy(
    value: Mapping[str, object],
    root: Path,
) -> GraphReasoningPolicy:
    return GraphReasoningPolicy(
        causal_relation_types=_required_str_tuple(
            value.get("causal_relation_types"),
            root,
            "graph.reasoning.causal_relation_types",
        ),
        compositional_relation_types=_required_str_tuple(
            value.get("compositional_relation_types"),
            root,
            "graph.reasoning.compositional_relation_types",
        ),
        comparison_markers=_required_str_tuple(
            value.get("comparison_markers"),
            root,
            "graph.reasoning.comparison_markers",
        ),
        semantic_relation_key_specs=_to_semantic_relation_key_specs(
            value.get("semantic_relation_key_specs"),
            root,
        ),
    )


@lru_cache(maxsize=8)
def load_policy_bundle(bundle_path: str | Path | None = None) -> QueryPolicyBundle:
    root = Path(bundle_path) if bundle_path is not None else default_policy_bundle_path()
    manifest = _read_json(root / "manifest.json", root)
    _verify_manifest(manifest, root)

    policy_payload = _read_json(root / str(manifest["policy_path"]), root)
    prompt_texts = _read_prompts(manifest, root)

    lexicon = _required_mapping(policy_payload, "lexicon", root)
    relation_payload = _required_mapping(policy_payload, "relations", root)
    scoring_payload = _required_mapping(policy_payload, "scoring", root)
    routing_payload = _required_mapping(policy_payload, "routing", root)
    graph_payload = _required_mapping(policy_payload, "graph", root)
    generation_payload = _required_mapping(policy_payload, "generation", root)
    graph_reasoning = _required_mapping(graph_payload, "reasoning", root)
    generation_rule_plan = _required_mapping(generation_payload, "rule_plan", root)
    generation_decision = _required_mapping(generation_payload, "decision", root)
    generation_fallback_answer = _required_mapping(generation_payload, "fallback_answer", root)
    entity_linker = _optional_mapping(
        relation_payload.get("entity_linker"),
        root,
        "relations.entity_linker",
    )

    _require_keys(
        relation_payload,
        ("preferred_relation_excluded_types", "relation_index_suffix_templates"),
        root,
        "relations",
    )
    _require_keys(graph_reasoning, _GRAPH_REASONING_KEYS, root, "graph.reasoning")
    graph_reasoning_policy = _to_graph_reasoning_policy(graph_reasoning, root)
    generation_rule_plan_policy = _to_generation_rule_plan(generation_rule_plan, root)
    generation_decision_policy = _to_generation_decision(generation_decision, root)
    _require_keys(
        generation_fallback_answer,
        _GENERATION_FALLBACK_ANSWER_KEYS,
        root,
        "generation.fallback_answer",
    )

    relation_types = _to_tuple(relation_payload.get("graph_relation_types"))
    preferred_relation_excluded_types = _to_tuple(
        relation_payload.get("preferred_relation_excluded_types")
    )
    relation_index_keywords = _to_tuple_map(
        relation_payload.get("relation_index_keywords"),
        root,
        "relations.relation_index_keywords",
    )
    relation_index_suffix_templates = _to_str_map(
        relation_payload.get("relation_index_suffix_templates"),
        root,
        "relations.relation_index_suffix_templates",
    )
    relation_query_markers = _to_tuple_map(
        relation_payload.get("relation_query_markers"),
        root,
        "relations.relation_query_markers",
    )
    _verify_relation_references(
        relation_types,
        preferred_relation_excluded_types,
        relation_index_keywords,
        relation_index_suffix_templates,
        relation_query_markers,
        graph_reasoning_policy,
        root,
    )

    metadata = PolicyMetadata(
        schema_version=str(manifest["schema_version"]),
        policy_version=str(manifest["policy_version"]),
        prompt_version=str(manifest["prompt_version"]),
        policy_hash=_hash_payload(policy_payload),
        prompt_hash=_hash_texts(prompt_texts),
        bundle_name=str(manifest["name"]),
    )

    return QueryPolicyBundle(
        metadata=metadata,
        lexicon=LexiconPolicy(
            term_sets=_to_tuple_map(lexicon.get("term_sets"), root, "lexicon.term_sets"),
            regex_rules=_to_tuple_map(lexicon.get("regex_rules"), root, "lexicon.regex_rules"),
        ),
        relations=RelationPolicy(
            graph_routing_strategies=_to_tuple(relation_payload.get("graph_routing_strategies")),
            graph_query_types=_to_tuple(relation_payload.get("graph_query_types")),
            graph_relation_types=relation_types,
            preferred_relation_excluded_types=preferred_relation_excluded_types,
            semantic_relation_hints=_to_str_map(
                relation_payload.get("semantic_relation_hints"),
                root,
                "relations.semantic_relation_hints",
            ),
            relation_index_keywords=relation_index_keywords,
            relation_index_suffix_templates=relation_index_suffix_templates,
            relation_query_markers=relation_query_markers,
            entity_linker_preferred_labels=_to_tuple(entity_linker.get("preferred_labels")),
            entity_linker_query_type_priorities=_to_tuple_map(
                entity_linker.get("query_type_priorities"),
                root,
                "relations.entity_linker.query_type_priorities",
            ),
            entity_linker_relation_priorities=_to_tuple_map(
                entity_linker.get("relation_priorities"),
                root,
                "relations.entity_linker.relation_priorities",
            ),
        ),
        scoring=ScoringPolicy(
            structural_relationship_factor=_float_field(
                scoring_payload,
                "structural_relationship_factor",
                0.5,
            ),
            length_norm_chars=_int_field(scoring_payload, "length_norm_chars", 140),
            weights=_to_float_map(scoring_payload.get("weights"), root, "scoring.weights"),
            boosts=_to_float_map(scoring_payload.get("boosts"), root, "scoring.boosts"),
        ),
        routing=RoutingPolicy(
            graph_first_query_types=_to_tuple(routing_payload.get("graph_first_query_types")),
            multi_hop_graph_first_relation_hits=_int_field(
                routing_payload,
                "multi_hop_graph_first_relation_hits",
                2,
            ),
            meaningful_constraint_fields=_to_tuple(
                routing_payload.get("meaningful_constraint_fields")
            ),
            validation_labels=_to_str_map(
                routing_payload.get("validation_labels"),
                root,
                "routing.validation_labels",
            ),
        ),
        graph=GraphPolicy(
            max_depth=_to_int_map(graph_payload.get("max_depth"), root, "graph.max_depth"),
            max_nodes=_to_int_map(graph_payload.get("max_nodes"), root, "graph.max_nodes"),
            sub_questions=_to_sub_question_items(graph_payload.get("sub_questions"), root),
            reasoning=graph_reasoning_policy,
        ),
        generation=GenerationPolicy(
            answer_types=_to_generation_answer_types(
                generation_payload.get("answer_types"),
                root,
                "generation.answer_types",
            ),
            relation_explanation_markers=_to_tuple(
                generation_payload.get("relation_explanation_markers")
            ),
            rule_plan=generation_rule_plan_policy,
            decision=generation_decision_policy,
            fallback_answer=_to_str_map(
                generation_fallback_answer,
                root,
                "generation.fallback_answer",
            ),
        ),
        runtime_defaults=_to_runtime_defaults(policy_payload.get("runtime_defaults"), root),
        prompts=PromptTemplates(
            query_planner=prompt_texts["query_planner"],
            answer_plan=prompt_texts["answer_plan"],
            answer_compose=prompt_texts["answer_compose"],
            answer_direct=prompt_texts["answer_direct"],
        ),
    )


def get_query_policy(bundle_path: str | Path | None = None) -> QueryPolicyBundle:
    return load_policy_bundle(bundle_path)

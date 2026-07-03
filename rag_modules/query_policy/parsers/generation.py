"""Generation policy parser."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from ..models import (
    GenerationAnswerTypePolicy,
    GenerationDecisionPolicy,
    GenerationDecisionReasonsPolicy,
    GenerationPolicy,
    GenerationRulePlanPolicy,
)
from .common import (
    float_field,
    mapping,
    require_keys,
    required_mapping,
    required_str_tuple,
    to_str_map,
    to_tuple,
)

_RULE_PLAN_KEYS = (
    "default_outline",
    "fallback_outline",
    "graph_caution",
    "missing_relation_evidence",
    "sparse_evidence",
    "missing_information_caution",
    "fallback_claim_template",
)

_DECISION_KEYS = ("default_answer_type", "high_pressure_margin", "reasons")

_DECISION_REASON_KEYS = (
    "two_stage_disabled",
    "no_route_analysis",
    "graph_without_analysis",
    "graph_rag",
    "combined_pressure",
    "high_pressure",
    "simple",
)

_FALLBACK_ANSWER_KEYS = (
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


def parse_generation(policy_payload: Mapping[str, object], root: Path) -> GenerationPolicy:
    payload = required_mapping(policy_payload, "generation", root)
    rule_plan = required_mapping(payload, "rule_plan", root, field_path="generation.rule_plan")
    decision = required_mapping(payload, "decision", root, field_path="generation.decision")
    fallback_answer = required_mapping(
        payload,
        "fallback_answer",
        root,
        field_path="generation.fallback_answer",
    )
    rule_plan_policy = _to_generation_rule_plan(rule_plan, root)
    decision_policy = _to_generation_decision(decision, root)
    require_keys(fallback_answer, _FALLBACK_ANSWER_KEYS, root, "generation.fallback_answer")

    return GenerationPolicy(
        answer_types=_to_generation_answer_types(
            payload.get("answer_types"),
            root,
            "generation.answer_types",
        ),
        relation_explanation_markers=to_tuple(payload.get("relation_explanation_markers")),
        rule_plan=rule_plan_policy,
        decision=decision_policy,
        fallback_answer=to_str_map(
            fallback_answer,
            root,
            "generation.fallback_answer",
        ),
    )


def _to_generation_answer_types(
    value: object,
    root: Path,
    field_path: str,
) -> dict[str, GenerationAnswerTypePolicy]:
    payload = mapping(value, root, field_path)
    result: dict[str, GenerationAnswerTypePolicy] = {}
    for answer_type, raw_config in payload.items():
        config_path = f"{field_path}.{answer_type}"
        config = mapping(raw_config, root, config_path)
        result[str(answer_type)] = GenerationAnswerTypePolicy(
            markers=to_tuple(config.get("markers"))
        )
    return result


def _to_generation_rule_plan(
    value: Mapping[str, object],
    root: Path,
) -> GenerationRulePlanPolicy:
    require_keys(value, _RULE_PLAN_KEYS, root, "generation.rule_plan")
    return GenerationRulePlanPolicy(
        default_outline=required_str_tuple(
            value.get("default_outline"), root, "generation.rule_plan.default_outline"
        ),
        fallback_outline=required_str_tuple(
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
    require_keys(value, _DECISION_KEYS, root, "generation.decision")
    reasons = required_mapping(value, "reasons", root, field_path="generation.decision.reasons")
    require_keys(
        reasons,
        _DECISION_REASON_KEYS,
        root,
        "generation.decision.reasons",
    )
    return GenerationDecisionPolicy(
        default_answer_type=str(value.get("default_answer_type") or "direct_answer"),
        high_pressure_margin=float_field(value, "high_pressure_margin", 0.12),
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

"""Generation policy parser."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from string import Formatter

from ..models import (
    AnswerWorkflowCopyPolicy,
    GenerationAnswerTypePolicy,
    GenerationDecisionPolicy,
    GenerationDecisionReasonsPolicy,
    GenerationPolicy,
    GenerationRulePlanPolicy,
    PolicyLoadError,
)
from .common import (
    float_field,
    mapping,
    optional_mapping,
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

_DECISION_KEYS = ("default_answer_type", "high_pressure_margin")

_DECISION_REASON_KEYS = (
    "two_stage_disabled",
    "no_route_analysis",
    "graph_without_analysis",
    "graph_rag",
    "combined_pressure",
    "high_pressure",
    "simple",
)

_ANSWER_WORKFLOW_TEMPLATE_VARIABLES = {
    "user_question_template": {"question"},
    "answer_complete_template": {"latency_seconds"},
    "strategy_summary_template": {
        "strategy_icon",
        "strategy",
        "complexity",
        "relationship_intensity",
    },
    "document_summary_template": {"document_count", "document_summaries"},
    "document_summary_total_template": {"document_count"},
}

_DECISION_REASON_DEFAULTS = {key: key for key in _DECISION_REASON_KEYS}

_FALLBACK_ANSWER_DEFAULTS = {
    "empty_evidence": "No evidence.",
    "heading": "Evidence-only answer:",
    "item_line": "{index}. {title} ({citation})",
    "matched_terms": "Matched terms: {matched_terms}",
    "graph_claim": "Graph evidence: {claim}",
    "text_claim": "Text evidence: {claim}",
    "constraint_reasons": "Constraints: {constraint_reasons}",
    "boundary": "Evidence-only boundary.",
    "model_unavailable": "Model unavailable.",
}

_ANSWER_WORKFLOW_COPY_DEFAULTS = {
    "no_evidence_answer": "No evidence.",
    "answer_failed": "Answer failed.",
    "user_question_template": "Question: {question}",
    "query_routing_started": "Running query routing...",
    "answer_generation_started": "Generating answer...",
    "streaming_interrupted_fallback": "Stream interrupted.",
    "answer_complete_template": "Done in {latency_seconds:.2f}s",
    "strategy_summary_template": (
        "{strategy_icon} Strategy: {strategy}\n"
        "Complexity: {complexity:.2f}, "
        "Relationship intensity: {relationship_intensity:.2f}"
    ),
    "strategy_icon_hybrid_traditional": "[HYBRID]",
    "strategy_icon_graph_rag": "[GRAPH]",
    "strategy_icon_combined": "[COMBINED]",
    "strategy_icon_default": "[ROUTE]",
    "document_summary_template": "Found {document_count} relevant documents: {document_summaries}",
    "document_summary_total_template": "\n    Total results: {document_count}",
    "unknown_entity_name": "unknown",
    "unknown_search_type": "unknown",
}


def parse_generation(policy_payload: Mapping[str, object], root: Path) -> GenerationPolicy:
    payload = required_mapping(policy_payload, "generation", root)
    rule_plan = required_mapping(payload, "rule_plan", root, field_path="generation.rule_plan")
    decision = required_mapping(payload, "decision", root, field_path="generation.decision")
    fallback_answer = optional_mapping(
        payload.get("fallback_answer"),
        root,
        "generation.fallback_answer",
    )
    answer_workflow_copy = optional_mapping(
        payload.get("answer_workflow_copy"),
        root,
        "generation.answer_workflow_copy",
    )
    rule_plan_policy = _to_generation_rule_plan(rule_plan, root)
    decision_policy = _to_generation_decision(decision, root)

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
            _with_defaults(fallback_answer, _FALLBACK_ANSWER_DEFAULTS),
            root,
            "generation.fallback_answer",
        ),
        answer_workflow_copy=_to_answer_workflow_copy(answer_workflow_copy, root),
        citation_label=str(payload.get("citation_label") or "Evidence"),
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
    reasons = _with_defaults(
        optional_mapping(
            value.get("reasons"),
            root,
            "generation.decision.reasons",
        ),
        _DECISION_REASON_DEFAULTS,
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


def _template_variables(template: str) -> set[str]:
    variables: set[str] = set()
    for _, field_name, _, _ in Formatter().parse(template):
        if field_name:
            variables.add(field_name.split(".", 1)[0].split("[", 1)[0])
    return variables


def _verify_answer_workflow_templates(
    value: Mapping[str, object],
    root: Path,
) -> None:
    for key, allowed_variables in _ANSWER_WORKFLOW_TEMPLATE_VARIABLES.items():
        actual_variables = _template_variables(str(value.get(key) or ""))
        unknown_variables = sorted(actual_variables - allowed_variables)
        if unknown_variables:
            unknown = unknown_variables[0]
            raise PolicyLoadError(
                f"Unsupported answer workflow copy variable: {key}.{unknown}",
                bundle_path=str(root),
                field_path=f"generation.answer_workflow_copy.{key}.{unknown}",
            )


def _to_answer_workflow_copy(
    value: Mapping[str, object],
    root: Path,
) -> AnswerWorkflowCopyPolicy:
    payload = _with_defaults(value, _ANSWER_WORKFLOW_COPY_DEFAULTS)
    _verify_answer_workflow_templates(payload, root)
    return AnswerWorkflowCopyPolicy(
        no_evidence_answer=str(payload.get("no_evidence_answer") or ""),
        answer_failed=str(payload.get("answer_failed") or ""),
        user_question_template=str(payload.get("user_question_template") or ""),
        query_routing_started=str(payload.get("query_routing_started") or ""),
        answer_generation_started=str(payload.get("answer_generation_started") or ""),
        streaming_interrupted_fallback=str(payload.get("streaming_interrupted_fallback") or ""),
        answer_complete_template=str(payload.get("answer_complete_template") or ""),
        strategy_summary_template=str(payload.get("strategy_summary_template") or ""),
        strategy_icon_hybrid_traditional=str(payload.get("strategy_icon_hybrid_traditional") or ""),
        strategy_icon_graph_rag=str(payload.get("strategy_icon_graph_rag") or ""),
        strategy_icon_combined=str(payload.get("strategy_icon_combined") or ""),
        strategy_icon_default=str(payload.get("strategy_icon_default") or ""),
        document_summary_template=str(payload.get("document_summary_template") or ""),
        document_summary_total_template=str(payload.get("document_summary_total_template") or ""),
        unknown_entity_name=str(
            value.get("unknown_entity_name") or payload.get("unknown_entity_name") or ""
        ),
        unknown_search_type=str(payload.get("unknown_search_type") or ""),
    )


def _with_defaults(
    value: Mapping[str, object],
    defaults: Mapping[str, object],
) -> dict[str, object]:
    return {**defaults, **{str(key): item for key, item in value.items()}}

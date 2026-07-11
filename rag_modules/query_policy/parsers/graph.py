"""Graph policy parser."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import cast

from ..models import (
    GraphPolicy,
    GraphReasoningPolicy,
    GraphSubQuestionCondition,
    GraphSubQuestionPolicy,
    PolicyLoadError,
    SemanticRelationKeySpec,
)
from .common import (
    mapping,
    optional_mapping,
    require_keys,
    required_mapping,
    required_str_tuple,
    to_int_map,
    to_tuple,
)

_SUB_QUESTION_CONDITION_KEYS = {
    "entities_present",
    "relation_types_any",
    "constraints_present",
    "relationship_intensity_at_least",
    "query_markers_any",
    "fallback",
}

_REQUIRED_REASONING_KEYS = (
    "causal_relation_types",
    "compositional_relation_types",
)


def parse_graph(policy_payload: Mapping[str, object], root: Path) -> GraphPolicy:
    payload = required_mapping(policy_payload, "graph", root)
    reasoning = required_mapping(payload, "reasoning", root, field_path="graph.reasoning")
    require_keys(reasoning, _REQUIRED_REASONING_KEYS, root, "graph.reasoning")
    return GraphPolicy(
        max_depth=to_int_map(payload.get("max_depth"), root, "graph.max_depth"),
        max_nodes=to_int_map(payload.get("max_nodes"), root, "graph.max_nodes"),
        sub_questions=_to_sub_question_items(payload.get("sub_questions"), root),
        reasoning=_to_graph_reasoning_policy(reasoning, root),
    )


def _to_sub_question_condition(
    value: object,
    root: Path,
    field_path: str,
) -> GraphSubQuestionCondition:
    payload = optional_mapping(value, root, field_path)
    unknown_keys = sorted(set(payload) - _SUB_QUESTION_CONDITION_KEYS)
    if unknown_keys:
        unknown_key = unknown_keys[0]
        raise PolicyLoadError(
            f"Unknown graph sub-question condition: {unknown_key}",
            bundle_path=str(root),
            field_path=f"{field_path}.{unknown_key}",
        )
    constraints_rule = payload.get("constraints_present")
    constraints_any = bool(constraints_rule) if isinstance(constraints_rule, bool) else False
    constraint_fields = () if isinstance(constraints_rule, bool) else to_tuple(constraints_rule)
    return GraphSubQuestionCondition(
        fallback=bool(payload.get("fallback", False)),
        entities_present=(
            bool(payload["entities_present"]) if "entities_present" in payload else None
        ),
        relation_types_any=to_tuple(payload.get("relation_types_any")),
        constraints_present=constraint_fields,
        constraints_present_any=constraints_any,
        relationship_intensity_at_least=(
            float(cast(float | int | str | bool, payload["relationship_intensity_at_least"]))
            if payload.get("relationship_intensity_at_least") is not None
            else None
        ),
        query_markers_any=to_tuple(payload.get("query_markers_any")),
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
        payload = mapping(item, root, field_path)
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


def _to_graph_reasoning_policy(
    value: Mapping[str, object],
    root: Path,
) -> GraphReasoningPolicy:
    return GraphReasoningPolicy(
        causal_relation_types=required_str_tuple(
            value.get("causal_relation_types"),
            root,
            "graph.reasoning.causal_relation_types",
        ),
        compositional_relation_types=required_str_tuple(
            value.get("compositional_relation_types"),
            root,
            "graph.reasoning.compositional_relation_types",
        ),
        comparison_markers=_optional_str_tuple(
            value.get("comparison_markers"),
            root,
            "graph.reasoning.comparison_markers",
        ),
        semantic_relation_key_specs=_to_semantic_relation_key_specs(
            value.get("semantic_relation_key_specs"),
            root,
        ),
    )


def _to_semantic_relation_key_specs(
    value: object,
    root: Path,
) -> dict[str, SemanticRelationKeySpec]:
    field_path = "graph.reasoning.semantic_relation_key_specs"
    if value is None:
        return {}
    payload = mapping(value, root, field_path)

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
        spec = mapping(raw_spec, root, spec_path)
        require_keys(spec, ("target_field", "key_fields"), root, spec_path)
        target_field = str(spec.get("target_field") or "").strip()
        if not target_field:
            raise PolicyLoadError(
                "Semantic relation key spec target_field is required",
                bundle_path=str(root),
                field_path=f"{spec_path}.target_field",
            )
        key_fields = required_str_tuple(spec.get("key_fields"), root, f"{spec_path}.key_fields")
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


def _optional_str_tuple(value: object, root: Path, field_path: str) -> tuple[str, ...]:
    if value is None:
        return ()
    return required_str_tuple(value, root, field_path)

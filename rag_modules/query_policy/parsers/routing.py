"""Routing policy parser."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import cast

from ..models import PolicyLoadError, RoutingPolicy, StrategyRoutingRule
from .common import int_field, mapping, required_mapping, str_field, to_str_map, to_tuple

_VALID_STRATEGIES = frozenset({"hybrid_traditional", "graph_rag", "combined"})


def _parse_strategy_rules(value: object, root: Path) -> tuple[StrategyRoutingRule, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise PolicyLoadError(
            "Routing strategy rules must be a list.",
            bundle_path=str(root),
            field_path="routing.strategy_rules",
        )
    rules: list[StrategyRoutingRule] = []
    for index, raw_rule in enumerate(value):
        field_path = f"routing.strategy_rules[{index}]"
        rule = mapping(raw_rule, root, field_path)
        strategy = str_field(rule, "strategy")
        if strategy not in _VALID_STRATEGIES:
            raise PolicyLoadError(
                "Routing strategy rule is invalid.",
                bundle_path=str(root),
                field_path=f"{field_path}.strategy",
            )
        relation_types_all = to_tuple(rule.get("relation_types_all"))
        relation_types_any = to_tuple(rule.get("relation_types_any"))
        if not relation_types_all and not relation_types_any:
            raise PolicyLoadError(
                "Routing strategy rule must define a relation-type condition.",
                bundle_path=str(root),
                field_path=field_path,
            )
        maximum_structural_hit_count = _optional_non_negative_int(
            rule.get("maximum_structural_hit_count"),
            root,
            f"{field_path}.maximum_structural_hit_count",
        )
        rules.append(
            StrategyRoutingRule(
                strategy=strategy,
                relation_types_all=relation_types_all,
                relation_types_any=relation_types_any,
                maximum_structural_hit_count=maximum_structural_hit_count,
            )
        )
    return tuple(rules)


def _optional_non_negative_int(value: object, root: Path, field_path: str) -> int | None:
    if value is None:
        return None
    try:
        result = int(cast(float | int | str | bool, value))
    except (TypeError, ValueError) as exc:
        raise PolicyLoadError(
            "Routing strategy rule limit must be an integer.",
            bundle_path=str(root),
            field_path=field_path,
        ) from exc
    if result < 0:
        raise PolicyLoadError(
            "Routing strategy rule limit must be non-negative.",
            bundle_path=str(root),
            field_path=field_path,
        )
    return result


def parse_routing(policy_payload: Mapping[str, object], root: Path) -> RoutingPolicy:
    payload = required_mapping(policy_payload, "routing", root)
    return RoutingPolicy(
        graph_first_query_types=to_tuple(payload.get("graph_first_query_types")),
        multi_hop_graph_first_relation_hits=int_field(
            payload,
            "multi_hop_graph_first_relation_hits",
            2,
        ),
        meaningful_constraint_fields=to_tuple(payload.get("meaningful_constraint_fields")),
        validation_labels=to_str_map(
            payload.get("validation_labels"),
            root,
            "routing.validation_labels",
        ),
        strategy_rules=_parse_strategy_rules(payload.get("strategy_rules"), root),
    )

"""Routing policy parser."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from ..models import RoutingPolicy
from .common import int_field, required_mapping, to_str_map, to_tuple


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
    )

"""Scoring policy parser."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from ..models import ScoringPolicy
from .common import float_field, int_field, required_mapping, to_float_map


def parse_scoring(policy_payload: Mapping[str, object], root: Path) -> ScoringPolicy:
    payload = required_mapping(policy_payload, "scoring", root)
    return ScoringPolicy(
        structural_relationship_factor=float_field(
            payload,
            "structural_relationship_factor",
            0.5,
        ),
        length_norm_chars=int_field(payload, "length_norm_chars", 140),
        weights=to_float_map(payload.get("weights"), root, "scoring.weights"),
        boosts=to_float_map(payload.get("boosts"), root, "scoring.boosts"),
    )

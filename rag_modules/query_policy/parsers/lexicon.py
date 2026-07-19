"""Lexicon policy parser."""

from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path

from ..models import LexiconPolicy, PolicyLoadError
from .common import required_mapping, to_tuple_map


def _validate_regex_rules(regex_rules: dict[str, tuple[str, ...]], root: Path) -> None:
    for group_name, patterns in regex_rules.items():
        for index, pattern in enumerate(patterns):
            field_path = f"lexicon.regex_rules.{group_name}[{index}]"
            try:
                compiled = re.compile(pattern)
            except re.error as exc:
                raise PolicyLoadError(
                    "Policy regex is invalid.",
                    bundle_path=str(root),
                    field_path=field_path,
                ) from exc
            if group_name == "pairwise_entity_patterns" and compiled.groups != 2:
                raise PolicyLoadError(
                    "Pairwise entity regex must define exactly two capture groups.",
                    bundle_path=str(root),
                    field_path=field_path,
                )
            if group_name == "entity_reference_patterns" and compiled.groups != 1:
                raise PolicyLoadError(
                    "Entity reference regex must define exactly one capture group.",
                    bundle_path=str(root),
                    field_path=field_path,
                )


def parse_lexicon(policy_payload: Mapping[str, object], root: Path) -> LexiconPolicy:
    payload = required_mapping(policy_payload, "lexicon", root)
    regex_rules = to_tuple_map(payload.get("regex_rules"), root, "lexicon.regex_rules")
    _validate_regex_rules(regex_rules, root)
    return LexiconPolicy(
        term_sets=to_tuple_map(payload.get("term_sets"), root, "lexicon.term_sets"),
        regex_rules=regex_rules,
    )

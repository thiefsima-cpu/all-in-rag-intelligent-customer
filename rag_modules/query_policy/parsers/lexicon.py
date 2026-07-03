"""Lexicon policy parser."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from ..models import LexiconPolicy
from .common import required_mapping, to_tuple_map


def parse_lexicon(policy_payload: Mapping[str, object], root: Path) -> LexiconPolicy:
    payload = required_mapping(policy_payload, "lexicon", root)
    return LexiconPolicy(
        term_sets=to_tuple_map(payload.get("term_sets"), root, "lexicon.term_sets"),
        regex_rules=to_tuple_map(payload.get("regex_rules"), root, "lexicon.regex_rules"),
    )

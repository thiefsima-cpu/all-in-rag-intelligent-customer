"""Load query policy defaults from JSON."""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Tuple


def _to_tuple(value: Any) -> Tuple[str, ...]:
    if isinstance(value, (list, tuple)):
        return tuple(str(item) for item in value if str(item).strip())
    if value is None:
        return ()
    text = str(value).strip()
    return (text,) if text else ()


def _to_tuple_map(value: Any) -> Dict[str, Tuple[str, ...]]:
    payload = dict(value or {})
    return {str(key): _to_tuple(items) for key, items in payload.items()}


def _to_runtime_defaults(value: Any) -> Dict[str, Dict[str, Any]]:
    payload = dict(value or {})
    return {str(section): dict(section_values or {}) for section, section_values in payload.items()}


@dataclass(frozen=True)
class QueryPolicy:
    graph_routing_strategies: Tuple[str, ...]
    graph_query_types: Tuple[str, ...]
    graph_relation_types: Tuple[str, ...]
    term_sets: Dict[str, Tuple[str, ...]]
    semantic_relation_hints: Dict[str, str]
    relation_index_keywords: Dict[str, Tuple[str, ...]]
    relation_query_markers: Dict[str, Tuple[str, ...]]
    entity_linker_preferred_labels: Tuple[str, ...]
    entity_linker_query_type_priorities: Dict[str, Tuple[str, ...]]
    entity_linker_relation_priorities: Dict[str, Tuple[str, ...]]
    regex_rules: Dict[str, Tuple[str, ...]]
    runtime_defaults: Dict[str, Dict[str, Any]]

    def term_group(self, name: str) -> Tuple[str, ...]:
        return tuple(self.term_sets.get(str(name), ()))

    def regex_group(self, name: str) -> Tuple[str, ...]:
        return tuple(self.regex_rules.get(str(name), ()))

    def runtime_section(self, name: str) -> Dict[str, Any]:
        return dict(self.runtime_defaults.get(str(name), {}))


def _policy_path() -> Path:
    return Path(__file__).with_name("defaults.json")


def _planner_prompt_path() -> Path:
    return Path(__file__).with_name("planner_prompt.txt")


@lru_cache(maxsize=1)
def get_query_policy() -> QueryPolicy:
    with _policy_path().open("r", encoding="utf-8") as file:
        payload = json.load(file)
    entity_linker = dict(payload.get("entity_linker") or {})
    return QueryPolicy(
        graph_routing_strategies=_to_tuple(payload.get("graph_routing_strategies")),
        graph_query_types=_to_tuple(payload.get("graph_query_types")),
        graph_relation_types=_to_tuple(payload.get("graph_relation_types")),
        term_sets=_to_tuple_map(payload.get("term_sets")),
        semantic_relation_hints={
            str(key): str(value)
            for key, value in dict(payload.get("semantic_relation_hints") or {}).items()
            if str(key).strip() and str(value).strip()
        },
        relation_index_keywords=_to_tuple_map(payload.get("relation_index_keywords")),
        relation_query_markers=_to_tuple_map(payload.get("relation_query_markers")),
        entity_linker_preferred_labels=_to_tuple(entity_linker.get("preferred_labels")),
        entity_linker_query_type_priorities=_to_tuple_map(
            entity_linker.get("query_type_priorities")
        ),
        entity_linker_relation_priorities=_to_tuple_map(entity_linker.get("relation_priorities")),
        regex_rules=_to_tuple_map(payload.get("regex_rules")),
        runtime_defaults=_to_runtime_defaults(payload.get("runtime_defaults")),
    )


@lru_cache(maxsize=1)
def get_planner_prompt_template() -> str:
    return _planner_prompt_path().read_text(encoding="utf-8")


def flatten_term_groups(*names: str) -> Tuple[str, ...]:
    policy = get_query_policy()
    merged: list[str] = []
    for name in names:
        merged.extend(policy.term_group(name))
    deduped: list[str] = []
    seen: set[str] = set()
    for item in merged:
        if item in seen:
            continue
        seen.add(item)
        deduped.append(item)
    return tuple(deduped)

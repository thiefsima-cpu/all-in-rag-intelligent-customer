"""Prompt construction and LLM response extraction for query planning."""

from __future__ import annotations

from ...query_policy import get_planner_prompt_template
from ..registry import GRAPH_QUERY_TYPES, GRAPH_RELATION_TYPES


def build_planning_prompt(query: str) -> str:
    graph_query_types_text = "\n".join(f"- {item}" for item in GRAPH_QUERY_TYPES)
    relation_types_text = "\n".join(f"- {item}" for item in GRAPH_RELATION_TYPES)
    preferred_relation_types_text = "\n".join(
        f"- {item}"
        for item in GRAPH_RELATION_TYPES
        if item not in {"REQUIRES", "BELONGS_TO_CATEGORY", "CONTAINS_STEP"}
    )
    return get_planner_prompt_template().format(
        graph_query_types_text=graph_query_types_text,
        relation_types_text=relation_types_text,
        preferred_relation_types_text=preferred_relation_types_text,
        query=query,
    )


def response_text(response: object) -> str:
    choices = getattr(response, "choices", None) or []
    if not choices:
        return ""
    message = getattr(choices[0], "message", None)
    content = getattr(message, "content", None)
    return str(content or "")


__all__ = ["build_planning_prompt", "response_text"]

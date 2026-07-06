"""Prompt construction and LLM response extraction for query planning."""

from __future__ import annotations

from ...query_policy import get_query_policy
from ...query_policy.models import QueryPolicyBundle
from ..registry import QueryUnderstandingRegistry, query_registry


def build_planning_prompt(
    query: str,
    *,
    policy_bundle: QueryPolicyBundle | None = None,
    registry: QueryUnderstandingRegistry | None = None,
) -> str:
    policy = policy_bundle or get_query_policy()
    active_registry = registry or query_registry(policy)
    graph_query_types_text = "\n".join(f"- {item}" for item in active_registry.graph_query_types)
    relation_types_text = "\n".join(f"- {item}" for item in active_registry.graph_relation_types)
    excluded_relation_types = set(policy.relations.preferred_relation_excluded_types)
    preferred_relation_types_text = "\n".join(
        f"- {item}"
        for item in active_registry.graph_relation_types
        if item not in excluded_relation_types
    )
    return policy.prompts.query_planner.format(
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

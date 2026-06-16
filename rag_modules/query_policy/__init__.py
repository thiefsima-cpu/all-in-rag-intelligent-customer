"""Data-driven policy access for query semantics and retrieval runtime."""

from .loader import (
    QueryPolicy,
    flatten_term_groups,
    get_planner_prompt_template,
    get_query_policy,
)

__all__ = [
    "QueryPolicy",
    "flatten_term_groups",
    "get_planner_prompt_template",
    "get_query_policy",
]

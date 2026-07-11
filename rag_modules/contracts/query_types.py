"""Query enum contracts and coercion helpers."""

from __future__ import annotations

from enum import Enum
from typing import Any

from ..kernel.routing import SearchStrategy


class GraphQueryType(str, Enum):
    ENTITY_RELATION = "entity_relation"
    MULTI_HOP = "multi_hop"
    SUBGRAPH = "subgraph"
    PATH_FINDING = "path_finding"
    CLUSTERING = "clustering"


class QueryPlannerMode(str, Enum):
    LLM = "llm"
    RULE_BASED = "rule_based"
    FAST_RULE = "fast_rule"
    FALLBACK_RULE = "fallback_rule"


VALID_GRAPH_QUERY_TYPES = {query_type.value for query_type in GraphQueryType}


def search_strategy(value: Any) -> SearchStrategy:
    if isinstance(value, SearchStrategy):
        return value
    return SearchStrategy(str(value or SearchStrategy.HYBRID_TRADITIONAL.value))


def graph_query_type(
    value: Any,
    default: GraphQueryType = GraphQueryType.SUBGRAPH,
) -> GraphQueryType:
    if isinstance(value, GraphQueryType):
        return value
    return GraphQueryType(str(value or default.value))


def graph_query_type_or_default(
    value: Any,
    default: GraphQueryType = GraphQueryType.SUBGRAPH,
) -> GraphQueryType:
    try:
        return graph_query_type(value, default)
    except ValueError:
        return default


def graph_query_type_value(value: GraphQueryType | str) -> str:
    if isinstance(value, GraphQueryType):
        return value.value
    return str(value or "")


def query_planner_mode(value: Any) -> QueryPlannerMode:
    if isinstance(value, QueryPlannerMode):
        return value
    try:
        return QueryPlannerMode(str(value or QueryPlannerMode.LLM.value))
    except ValueError:
        return QueryPlannerMode.LLM


__all__ = [
    "GraphQueryType",
    "QueryPlannerMode",
    "VALID_GRAPH_QUERY_TYPES",
    "graph_query_type",
    "graph_query_type_or_default",
    "graph_query_type_value",
    "query_planner_mode",
    "search_strategy",
]

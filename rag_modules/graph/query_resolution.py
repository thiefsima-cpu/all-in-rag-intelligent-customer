"""
Graph query resolution and decomposition.
"""

from __future__ import annotations

from typing import Any, Dict, List

from ..contracts import QueryPlan, QuerySemanticRuntimeSettings
from ..query_policy import get_query_policy
from ..query_understanding import (
    estimate_query_complexity,
    infer_graph_max_depth,
    infer_graph_max_nodes,
    infer_query_semantic_profile,
)
from .query_intent import GraphQueryIntent, infer_graph_query_intent
from .retrieval_types import GraphQuery, QueryType


def _coerce_constraints(value: Any) -> Dict[str, Any]:
    if hasattr(value, "to_dict"):
        return dict(value.to_dict())
    return dict(value or {})


class GraphQueryFactory:
    """Build executable graph query objects from plans and heuristic intent."""

    def __init__(self, *, semantic_settings: QuerySemanticRuntimeSettings | None = None):
        self.semantic_settings = semantic_settings or QuerySemanticRuntimeSettings()
        self.graph_policy = get_query_policy().graph

    def understand_graph_query(self, query: str) -> GraphQuery:
        return self.graph_query_from_intent(
            infer_graph_query_intent(query, semantic_settings=self.semantic_settings),
            query,
        )

    def graph_query_from_plan(self, plan: QueryPlan) -> GraphQuery:
        try:
            query_type = QueryType(plan.graph_query_type)
        except ValueError:
            query_type = QueryType.SUBGRAPH

        source_entities = (
            plan.source_entities or plan.entity_keywords or plan.topic_keywords or [plan.query]
        )
        return GraphQuery(
            query_type=query_type,
            source_entities=list(dict.fromkeys(source_entities or [])),
            target_entities=list(dict.fromkeys(plan.target_entities or [])),
            relation_types=list(dict.fromkeys(plan.relation_types or [])),
            max_depth=max(
                1,
                min(
                    int(
                        plan.max_depth
                        or infer_graph_max_depth(query_type.value, settings=self.semantic_settings)
                    ),
                    self.semantic_settings.graph_query_max_depth_cap,
                ),
            ),
            max_nodes=infer_graph_max_nodes(query_type.value, settings=self.semantic_settings),
            constraints=_coerce_constraints(plan.constraints),
        )

    def graph_query_from_intent(self, intent: GraphQueryIntent, query: str) -> GraphQuery:
        try:
            query_type = QueryType(intent.query_type)
        except ValueError:
            query_type = QueryType.SUBGRAPH

        source_entities = list(dict.fromkeys(intent.source_entities or []))
        if not source_entities and query:
            source_entities = [
                query[: self.semantic_settings.graph_query_fallback_name_chars].strip() or query
            ]

        return GraphQuery(
            query_type=query_type,
            source_entities=source_entities,
            target_entities=list(dict.fromkeys(intent.target_entities or [])),
            relation_types=list(dict.fromkeys(intent.relation_types or [])),
            max_depth=max(
                1,
                min(
                    int(
                        intent.max_depth
                        or infer_graph_max_depth(query_type.value, settings=self.semantic_settings)
                    ),
                    self.semantic_settings.graph_query_max_depth_cap,
                ),
            ),
            max_nodes=infer_graph_max_nodes(query_type.value, settings=self.semantic_settings),
            constraints=_coerce_constraints(intent.constraints),
        )

    def adaptive_query_planning(self, query: str) -> List[GraphQuery]:
        base_plan = self.understand_graph_query(query)
        complexity_score = self.analyze_query_complexity(query)
        query_plans = [base_plan]

        if (
            base_plan.query_type == QueryType.MULTI_HOP
            and complexity_score >= self.semantic_settings.adaptive_multi_hop_subgraph_threshold
        ):
            query_plans.insert(
                0,
                GraphQuery(
                    query_type=QueryType.SUBGRAPH,
                    source_entities=list(base_plan.source_entities),
                    target_entities=[],
                    relation_types=list(base_plan.relation_types),
                    max_depth=self.semantic_settings.adaptive_subgraph_max_depth,
                    max_nodes=self.semantic_settings.adaptive_subgraph_max_nodes,
                    constraints=dict(base_plan.constraints),
                ),
            )
        elif (
            base_plan.query_type in (QueryType.SUBGRAPH, QueryType.CLUSTERING)
            and complexity_score >= self.semantic_settings.adaptive_subgraph_multi_hop_threshold
        ):
            query_plans.append(
                GraphQuery(
                    query_type=QueryType.MULTI_HOP,
                    source_entities=list(base_plan.source_entities),
                    target_entities=list(base_plan.target_entities),
                    relation_types=list(base_plan.relation_types),
                    max_depth=max(
                        base_plan.max_depth, self.semantic_settings.adaptive_multi_hop_max_depth
                    ),
                    max_nodes=self.semantic_settings.adaptive_multi_hop_max_nodes,
                    constraints=dict(base_plan.constraints),
                )
            )
        elif (
            base_plan.query_type == QueryType.ENTITY_RELATION
            and complexity_score
            >= self.semantic_settings.adaptive_entity_relation_multi_hop_threshold
        ):
            query_plans.append(
                GraphQuery(
                    query_type=QueryType.MULTI_HOP,
                    source_entities=list(base_plan.source_entities),
                    target_entities=list(base_plan.target_entities),
                    relation_types=list(base_plan.relation_types),
                    max_depth=self.semantic_settings.adaptive_entity_relation_max_depth,
                    max_nodes=self.semantic_settings.adaptive_entity_relation_max_nodes,
                    constraints=dict(base_plan.constraints),
                )
            )

        return query_plans

    def analyze_query_complexity(self, query: str) -> float:
        return estimate_query_complexity(query, settings=self.semantic_settings)

    def decompose_graph_question(self, query: str, graph_query: GraphQuery) -> List[str]:
        profile = infer_query_semantic_profile(query, settings=self.semantic_settings)
        entities = list(
            dict.fromkeys((graph_query.source_entities or []) + (graph_query.target_entities or []))
        )
        relation_types = graph_query.relation_types or profile.relation_types or []
        sub_questions: List[str] = []
        fallback_rules: list[dict[str, Any]] = []

        for rule in self.graph_policy.sub_questions:
            when = dict(rule.get("when") or {})
            if when.get("fallback"):
                fallback_rules.append(rule)
                continue
            if _sub_question_rule_matches(
                when,
                query=query,
                profile=profile,
                entities=entities,
                relation_types=relation_types,
            ):
                sub_questions.append(
                    _render_sub_question(
                        rule,
                        query=query,
                        entities=entities,
                        relation_types=relation_types,
                    )
                )

        if not sub_questions:
            for rule in fallback_rules:
                sub_questions.append(
                    _render_sub_question(
                        rule,
                        query=query,
                        entities=entities,
                        relation_types=relation_types,
                    )
                )
                break
        return list(dict.fromkeys(item for item in sub_questions if item))[:6]


def _sub_question_rule_matches(
    when: Dict[str, Any],
    *,
    query: str,
    profile,
    entities: List[str],
    relation_types: List[str],
) -> bool:
    if not when:
        return False
    supported_keys = {
        "entities_present",
        "relation_types_any",
        "constraints_present",
        "relationship_intensity_at_least",
        "query_markers_any",
        "fallback",
    }
    if set(when) - supported_keys:
        return False
    if "entities_present" in when and bool(entities) != bool(when.get("entities_present")):
        return False
    relation_type_rules = _string_list(when.get("relation_types_any"))
    if relation_type_rules and not any(relation in relation_types for relation in relation_type_rules):
        return False
    constraint_rules = when.get("constraints_present")
    if constraint_rules is not None and not _constraints_present(profile.constraints, constraint_rules):
        return False
    threshold = when.get("relationship_intensity_at_least")
    if threshold is not None and profile.relationship_intensity < float(threshold):
        return False
    query_markers = _string_list(when.get("query_markers_any"))
    if query_markers and not any(marker in query for marker in query_markers):
        return False
    return not bool(when.get("fallback"))


def _render_sub_question(
    rule: Dict[str, Any],
    *,
    query: str,
    entities: List[str],
    relation_types: List[str],
) -> str:
    template = str(rule.get("template") or "").strip()
    if not template:
        return ""
    return template.format(
        query=query,
        entities=", ".join(entities[:4]),
        relation_types=", ".join(relation_types),
    )


def _constraints_present(constraints: Dict[str, Any], rule: Any) -> bool:
    if isinstance(rule, bool):
        return bool(rule) and _any_constraint_present(constraints)
    for field_name in _string_list(rule):
        value = constraints.get(field_name)
        if field_name == "time" and isinstance(value, dict):
            if any(item is not None for item in value.values()):
                return True
            continue
        if value:
            return True
    return False


def _any_constraint_present(constraints: Dict[str, Any]) -> bool:
    for key, value in constraints.items():
        if key == "time" and isinstance(value, dict):
            if any(item is not None for item in value.values()):
                return True
            continue
        if value:
            return True
    return False


def _string_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, (list, tuple)):
        return [str(item).strip() for item in value if str(item).strip()]
    return [str(value).strip()] if str(value).strip() else []

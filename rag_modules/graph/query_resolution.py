"""
Graph query resolution and decomposition.
"""

from __future__ import annotations

from typing import Any, Dict, List

from ..query_understanding import (
    QueryPlan,
    estimate_query_complexity,
    infer_graph_max_depth,
    infer_graph_max_nodes,
    infer_query_semantic_profile,
)
from ..retrieval.runtime_profile import QuerySemanticRuntimeSettings
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

        if entities:
            sub_questions.append(
                "Find the direct graph relations around: " + ", ".join(entities[:4])
            )
        if any(rel in relation_types for rel in ("HAS_FLAVOR", "CONTRIBUTES_TO")):
            sub_questions.append(
                "Surface ingredient, seasoning, or step evidence that contributes to flavor."
            )
        if "USES_TECHNIQUE" in relation_types:
            sub_questions.append(
                "Show how techniques affect texture, doneness, or final dish outcome."
            )
        if (
            any(rel in relation_types for rel in ("HAS_TIME_PROFILE", "HAS_DIFFICULTY_LEVEL"))
            or profile.constraints.get("time")
            or any(
                term in (profile.constraints.get("preference_terms") or [])
                for term in ("simple", "quick", "beginner", "easy")
            )
        ):
            sub_questions.append("Verify whether time and difficulty constraints are satisfied.")
        if (
            profile.relationship_intensity
            >= self.semantic_settings.reasoning_relationship_threshold
            or any(term in query for term in ("why", "reason", "impact", "relationship"))
        ):
            sub_questions.append(
                "Assemble multi-hop paths that explain causal or associative chains."
            )

        has_constraints = bool(
            profile.constraints.get("include_terms")
            or profile.constraints.get("exclude_terms")
            or profile.constraints.get("ingredients")
            or profile.constraints.get("excluded_ingredients")
            or profile.constraints.get("cuisine_terms")
            or profile.constraints.get("excluded_cuisine_terms")
            or profile.constraints.get("category_terms")
            or profile.constraints.get("health_terms")
            or profile.constraints.get("preference_terms")
            or any(value is not None for value in (profile.constraints.get("time") or {}).values())
            or profile.constraints.get("needs_recipe_recommendation")
        )
        if has_constraints:
            sub_questions.append(
                "Check whether graph evidence satisfies user constraints and preferences."
            )

        if not sub_questions:
            sub_questions.append(
                "Retrieve recipes, ingredients, steps, and semantic graph relations relevant to the question."
            )
        return sub_questions[:6]

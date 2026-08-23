from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from rag_modules.contracts import GraphQueryType, QuerySemanticProfile, QuerySemanticRuntimeSettings
from rag_modules.contracts.graph import GraphQuery
from rag_modules.graph.query_resolution import (
    GraphQueryFactory,
    _any_constraint_present,
    _constraints_present,
    _sub_question_rule_matches,
)
from rag_modules.query_policy.models import GraphSubQuestionCondition, GraphSubQuestionPolicy
from tests.configuration_test_helpers import build_test_config


class _Constraints:
    def to_dict(self) -> dict[str, object]:
        return {"diet": "vegan"}


def _factory() -> GraphQueryFactory:
    return GraphQueryFactory(
        semantic_settings=QuerySemanticRuntimeSettings.from_config(build_test_config())
    )


def _query(query_type: GraphQueryType) -> GraphQuery:
    return GraphQuery(
        query_type=query_type,
        source_entities=["tofu"],
        target_entities=["pepper"],
        relation_types=["USES"],
        max_depth=2,
        constraints={"diet": "vegan"},
    )


def test_factory_normalizes_invalid_plan_and_intent_boundaries() -> None:
    factory = _factory()
    plan = SimpleNamespace(
        graph_query_type="invalid",
        source_entities=[],
        entity_keywords=["tofu", "tofu"],
        topic_keywords=["fallback"],
        query="query fallback",
        target_entities=["pepper", "pepper"],
        relation_types=["USES", "USES"],
        max_depth=999,
        constraints=_Constraints(),
    )

    from_plan = factory.graph_query_from_plan(plan)
    from_intent = factory.graph_query_from_intent(
        SimpleNamespace(
            query_type="invalid",
            source_entities=[],
            target_entities=["target", "target"],
            relation_types=[],
            max_depth=0,
            constraints={"time": {"max": 20}},
        ),
        "  a deliberately long fallback query  ",
    )

    assert from_plan.query_type is GraphQueryType.SUBGRAPH
    assert from_plan.source_entities == ["tofu"]
    assert from_plan.target_entities == ["pepper"]
    assert from_plan.constraints == {"diet": "vegan"}
    assert from_plan.max_depth == factory.semantic_settings.graph_query_max_depth_cap
    assert from_intent.query_type is GraphQueryType.SUBGRAPH
    assert from_intent.source_entities
    assert (
        len(from_intent.source_entities[0])
        <= factory.semantic_settings.graph_query_fallback_name_chars
    )


@pytest.mark.parametrize(
    ("query_type", "expected_types"),
    [
        (GraphQueryType.MULTI_HOP, [GraphQueryType.SUBGRAPH, GraphQueryType.MULTI_HOP]),
        (GraphQueryType.SUBGRAPH, [GraphQueryType.SUBGRAPH, GraphQueryType.MULTI_HOP]),
        (
            GraphQueryType.ENTITY_RELATION,
            [GraphQueryType.ENTITY_RELATION, GraphQueryType.MULTI_HOP],
        ),
        (GraphQueryType.PATH_FINDING, [GraphQueryType.PATH_FINDING]),
    ],
)
def test_adaptive_planning_selects_each_runtime_path(
    query_type: GraphQueryType,
    expected_types: list[GraphQueryType],
) -> None:
    factory = _factory()
    with (
        patch.object(factory, "understand_graph_query", return_value=_query(query_type)),
        patch.object(factory, "analyze_query_complexity", return_value=1.0),
    ):
        plans = factory.adaptive_query_planning("complex query")

    assert [plan.query_type for plan in plans] == expected_types


def test_sub_question_conditions_cover_all_guards_and_constraint_shapes() -> None:
    profile = QuerySemanticProfile(
        constraints={
            "temporal_filters": {"max_duration_minutes": 20},
            "extension": {"preference_terms": ["vegan"]},
        },
        relationship_intensity=0.8,
    )
    common = {
        "query": "why tofu",
        "profile": profile,
        "entities": ["tofu"],
        "relation_types": ["USES"],
    }

    assert not _sub_question_rule_matches(GraphSubQuestionCondition(), **common)
    assert not _sub_question_rule_matches(
        GraphSubQuestionCondition(entities_present=False), **common
    )
    assert not _sub_question_rule_matches(
        GraphSubQuestionCondition(relation_types_any=("CAUSES",)), **common
    )
    assert not _sub_question_rule_matches(
        GraphSubQuestionCondition(constraints_present=("allergen",)), **common
    )
    assert not _sub_question_rule_matches(
        GraphSubQuestionCondition(relationship_intensity_at_least=0.9), **common
    )
    assert not _sub_question_rule_matches(
        GraphSubQuestionCondition(query_markers_any=("how",)), **common
    )
    assert not _sub_question_rule_matches(
        GraphSubQuestionCondition(fallback=True, entities_present=True), **common
    )
    assert _sub_question_rule_matches(
        GraphSubQuestionCondition(
            entities_present=True,
            relation_types_any=("USES",),
            constraints_present=("temporal_filters.max_duration_minutes",),
            relationship_intensity_at_least=0.7,
            query_markers_any=("why",),
        ),
        **common,
    )
    assert _constraints_present(
        profile.constraints, GraphSubQuestionCondition(constraints_present_any=True)
    )
    assert not _constraints_present(
        {"temporal_filters": {"min": None}},
        GraphSubQuestionCondition(constraints_present=("temporal_filters.min",)),
    )
    assert _any_constraint_present({"temporal_filters": {"min": None}, "diet": "vegan"})
    assert not _any_constraint_present({"temporal_filters": {"min": None}, "diet": ""})


def test_decomposition_uses_matching_rules_then_fallback_and_deduplicates() -> None:
    factory = _factory()
    matching = GraphSubQuestionPolicy(
        id="matching",
        template="inspect {entities}",
        when=GraphSubQuestionCondition(entities_present=True),
    )
    duplicate = GraphSubQuestionPolicy(
        id="duplicate",
        template="inspect {entities}",
        when=GraphSubQuestionCondition(relation_types_any=("USES",)),
    )
    fallback = GraphSubQuestionPolicy(
        id="fallback",
        template="fallback {query}",
        when=GraphSubQuestionCondition(fallback=True),
    )
    profile = QuerySemanticProfile(relation_types=["USES"])
    graph_query = _query(GraphQueryType.ENTITY_RELATION)

    with patch(
        "rag_modules.graph.query_resolution.infer_query_semantic_profile", return_value=profile
    ):
        factory.graph_policy = SimpleNamespace(sub_questions=(matching, duplicate, fallback))
        assert factory.decompose_graph_question("why tofu", graph_query) == ["inspect tofu, pepper"]

        factory.graph_policy = SimpleNamespace(sub_questions=(fallback,))
        assert factory.decompose_graph_question("why tofu", graph_query) == ["fallback why tofu"]

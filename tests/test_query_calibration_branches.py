from __future__ import annotations

from unittest.mock import patch

import pytest

from rag_modules.contracts import (
    GraphQueryType,
    QueryPlan,
    QuerySemanticProfile,
    QuerySemanticRuntimeSettings,
)
from rag_modules.contracts.query_constraints import QueryConstraints
from rag_modules.kernel.routing import SearchStrategy
from rag_modules.query_understanding.planning.calibration import (
    QueryPlanCalibrator,
    _graph_query_type_enum,
    _graph_query_type_value,
    _strategy_value,
)
from tests.configuration_test_helpers import build_test_config


def _calibrator() -> QueryPlanCalibrator:
    return QueryPlanCalibrator(QuerySemanticRuntimeSettings.from_config(build_test_config()))


def test_calibration_value_helpers_accept_enums_strings_and_invalid_values() -> None:
    assert _strategy_value(SearchStrategy.GRAPH_RAG) == "graph_rag"
    assert _strategy_value("") == "hybrid_traditional"
    assert _graph_query_type_value(GraphQueryType.SUBGRAPH) == "subgraph"
    assert _graph_query_type_value("") == ""
    assert _graph_query_type_enum(GraphQueryType.CLUSTERING) is GraphQueryType.CLUSTERING
    assert _graph_query_type_enum("invalid") is GraphQueryType.ENTITY_RELATION


def test_meaningful_constraints_handles_recommendation_boolean_values_and_empty_fields() -> None:
    calibrator = _calibrator()

    assert calibrator.has_meaningful_constraints(
        QueryConstraints(), QuerySemanticProfile(needs_recipe_recommendation=True)
    )
    assert calibrator.has_meaningful_constraints(
        QueryConstraints(ingredients=["tofu"]), QuerySemanticProfile()
    )
    assert calibrator.has_meaningful_constraints(
        QueryConstraints(needs_recipe_recommendation=True), QuerySemanticProfile()
    )
    assert not calibrator.has_meaningful_constraints(
        QueryConstraints(needs_recipe_recommendation=False), QuerySemanticProfile()
    )


@pytest.mark.parametrize(
    ("profile", "expected"),
    [
        (QuerySemanticProfile(query_type=GraphQueryType.PATH_FINDING), True),
        (QuerySemanticProfile(query_type=GraphQueryType.ENTITY_RELATION), False),
        (
            QuerySemanticProfile(query_type=GraphQueryType.MULTI_HOP, relation_hits=["one", "two"]),
            True,
        ),
        (
            QuerySemanticProfile(
                query_type=GraphQueryType.MULTI_HOP, structural_hits=["one", "two"]
            ),
            True,
        ),
        (
            QuerySemanticProfile(query_type=GraphQueryType.MULTI_HOP, relationship_intensity=1.0),
            True,
        ),
        (
            QuerySemanticProfile(query_type=GraphQueryType.MULTI_HOP, relationship_intensity=0.0),
            False,
        ),
    ],
)
def test_graph_first_profile_covers_direct_and_multi_hop_signals(
    profile: QuerySemanticProfile, expected: bool
) -> None:
    assert _calibrator().is_graph_first_profile(profile) is expected


def test_strategy_resolution_covers_graph_constraint_pressure_and_fallbacks() -> None:
    calibrator = _calibrator()
    graph_first = QuerySemanticProfile(query_type=GraphQueryType.SUBGRAPH)
    neutral = QuerySemanticProfile(
        query_type=GraphQueryType.ENTITY_RELATION, relationship_intensity=0.0
    )
    constrained = QueryConstraints(ingredients=["tofu"])
    empty = QueryConstraints()

    assert (
        calibrator.resolve_strategy(
            current_strategy="invalid",
            profile=graph_first,
            constraints=empty,
            complexity=0.0,
            relationship_intensity=0.0,
        )
        == SearchStrategy.GRAPH_RAG.value
    )
    assert (
        calibrator.resolve_strategy(
            current_strategy="invalid",
            profile=graph_first,
            constraints=constrained,
            complexity=0.0,
            relationship_intensity=0.0,
        )
        == SearchStrategy.COMBINED.value
    )
    assert (
        calibrator.resolve_strategy(
            current_strategy=SearchStrategy.HYBRID_TRADITIONAL,
            profile=neutral,
            constraints=constrained,
            complexity=1.0,
            relationship_intensity=1.0,
        )
        == SearchStrategy.COMBINED.value
    )
    assert (
        calibrator.resolve_strategy(
            current_strategy=SearchStrategy.COMBINED,
            profile=neutral,
            constraints=empty,
            complexity=0.0,
            relationship_intensity=0.0,
        )
        == SearchStrategy.HYBRID_TRADITIONAL.value
    )
    assert (
        calibrator.resolve_strategy(
            current_strategy=SearchStrategy.HYBRID_TRADITIONAL,
            profile=neutral,
            constraints=empty,
            complexity=0.0,
            relationship_intensity=0.0,
        )
        == SearchStrategy.HYBRID_TRADITIONAL.value
    )
    assert (
        calibrator.resolve_strategy(
            current_strategy="invalid",
            profile=neutral,
            constraints=constrained,
            complexity=0.0,
            relationship_intensity=0.0,
        )
        == SearchStrategy.COMBINED.value
    )
    assert (
        calibrator.resolve_strategy(
            current_strategy="invalid",
            profile=neutral,
            constraints=empty,
            complexity=0.0,
            relationship_intensity=0.0,
        )
        == SearchStrategy.HYBRID_TRADITIONAL.value
    )


def test_graph_query_type_resolution_prefers_profile_then_valid_current_type() -> None:
    calibrator = _calibrator()

    assert (
        calibrator.resolve_graph_query_type(
            GraphQueryType.ENTITY_RELATION,
            QuerySemanticProfile(query_type=GraphQueryType.PATH_FINDING),
        )
        is GraphQueryType.PATH_FINDING
    )
    assert (
        calibrator.resolve_graph_query_type(
            GraphQueryType.SUBGRAPH,
            QuerySemanticProfile(query_type=GraphQueryType.MULTI_HOP, relationship_intensity=1.0),
        )
        is GraphQueryType.MULTI_HOP
    )
    assert (
        calibrator.resolve_graph_query_type(
            GraphQueryType.ENTITY_RELATION,
            QuerySemanticProfile(query_type=GraphQueryType.MULTI_HOP, relationship_intensity=0.0),
        )
        is GraphQueryType.ENTITY_RELATION
    )
    assert (
        calibrator.resolve_graph_query_type(
            "invalid", QuerySemanticProfile(query_type=GraphQueryType.MULTI_HOP)
        )
        is GraphQueryType.MULTI_HOP
    )


def test_calibrate_merges_semantics_fills_keywords_and_records_changes() -> None:
    calibrator = _calibrator()
    plan = QueryPlan(
        query="tofu pepper relationship",
        complexity=0.1,
        relationship_intensity=0.1,
        strategy=SearchStrategy.HYBRID_TRADITIONAL,
        graph_query_type=GraphQueryType.SUBGRAPH,
        source_entities=[],
        entity_keywords=[],
        topic_keywords=[],
        target_entities=[],
        relation_types=["USES"],
        max_depth=0,
    )
    profile = QuerySemanticProfile(
        query=plan.query,
        query_type=GraphQueryType.MULTI_HOP,
        source_entities=["tofu"],
        target_entities=["pepper"],
        entity_keywords=["tofu"],
        topic_keywords=["texture"],
        relation_types=["USES", "CONTRIBUTES_TO"],
        complexity=0.9,
        relationship_intensity=0.9,
        reasoning_required=True,
        needs_recipe_recommendation=True,
    )

    with patch(
        "rag_modules.query_understanding.planning.calibration.infer_query_semantic_profile",
        return_value=profile,
    ):
        calibrator.calibrate(plan)

    assert plan.strategy is SearchStrategy.COMBINED
    assert plan.graph_query_type is GraphQueryType.MULTI_HOP
    assert plan.entity_keywords == ["tofu"]
    assert plan.topic_keywords == ["texture"]
    assert plan.target_entities == ["pepper"]
    assert plan.source_entities == ["tofu"]
    assert plan.relation_types == ["USES", "CONTRIBUTES_TO"]
    assert plan.reasoning_required is True
    assert any("calibrated_strategy" in error for error in plan.validation_errors)
    assert any("calibrated_graph_query_type" in error for error in plan.validation_errors)
    assert any("calibrated_source_entities" in error for error in plan.validation_errors)


def test_calibrate_preserves_existing_valid_plan_fields() -> None:
    calibrator = _calibrator()
    plan = QueryPlan(
        query="simple tofu",
        strategy=SearchStrategy.HYBRID_TRADITIONAL,
        graph_query_type=GraphQueryType.ENTITY_RELATION,
        source_entities=["tofu"],
        target_entities=["pepper"],
        entity_keywords=["tofu"],
        topic_keywords=["texture"],
        relation_types=["USES"],
        max_depth=2,
    )
    profile = QuerySemanticProfile(
        query=plan.query,
        query_type=GraphQueryType.ENTITY_RELATION,
        relation_types=["USES"],
        complexity=0.1,
        relationship_intensity=0.1,
    )

    with patch(
        "rag_modules.query_understanding.planning.calibration.infer_query_semantic_profile",
        return_value=profile,
    ):
        calibrator.calibrate(plan)

    assert plan.strategy is SearchStrategy.HYBRID_TRADITIONAL
    assert plan.graph_query_type is GraphQueryType.ENTITY_RELATION
    assert plan.validation_errors == []

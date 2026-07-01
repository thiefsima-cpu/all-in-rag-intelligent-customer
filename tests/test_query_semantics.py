from __future__ import annotations

import unittest
from pathlib import Path

from rag_modules.contracts import (
    GraphQueryType,
    QueryPlan,
    QueryPlannerMode,
    QueryPlannerRuntimeSettings,
    QuerySemanticProfile,
    QuerySemanticRuntimeSettings,
)
from rag_modules.query_understanding import (
    QueryPlanner,
    infer_query_constraints,
    infer_query_semantic_profile,
)
from rag_modules.runtime import SearchStrategy


class _DummyCompletions:
    def create(self, **_: object) -> None:
        raise AssertionError("LLM planning should not be used in these unit tests.")


class _DummyChat:
    def __init__(self) -> None:
        self.completions = _DummyCompletions()


class _DummyLLM:
    def __init__(self) -> None:
        self.chat = _DummyChat()


class _FailingPlannerClient:
    def create_completion(self, **_: object) -> None:
        raise RuntimeError("private-planner-error")


class QuerySemanticsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.semantic_settings = QuerySemanticRuntimeSettings()
        self.planner = QueryPlanner(
            _DummyLLM(),
            settings=QueryPlannerRuntimeSettings(fast_rule_planning=True),
            semantic_settings=self.semantic_settings,
        )

    def test_complex_relation_query_prefers_graph_rag(self) -> None:
        query = (
            "为什么水煮肉片能形成麻辣鲜香的口味？"
            "它和豆瓣酱、花椒、辣椒、垫底蔬菜、肉片上浆这些食材和步骤之间有什么关系？"
        )

        profile = infer_query_semantic_profile(query, settings=self.semantic_settings)
        plan = self.planner.rule_based_plan(query)

        self.assertGreaterEqual(profile.complexity, 0.7)
        self.assertGreaterEqual(profile.relationship_intensity, 0.7)
        self.assertIs(plan.strategy, SearchStrategy.GRAPH_RAG)
        self.assertEqual(plan.graph_query_type, "multi_hop")
        self.assertIn(
            "水煮肉片",
            list(plan.entity_keywords) + list(plan.source_entities) + list(plan.target_entities),
        )

    def test_simple_recipe_query_prefers_hybrid(self) -> None:
        plan = self.planner.rule_based_plan("宫保鸡丁怎么做？")

        self.assertIs(plan.strategy, SearchStrategy.HYBRID_TRADITIONAL)
        self.assertEqual(plan.graph_query_type, "entity_relation")
        self.assertLess(plan.relationship_intensity, 0.7)

    def test_planner_failure_uses_stable_fallback_reason(self) -> None:
        planner = QueryPlanner(
            _FailingPlannerClient(),
            settings=QueryPlannerRuntimeSettings(fast_rule_planning=False),
            semantic_settings=self.semantic_settings,
        )

        plan = planner.plan("recommend tofu")

        self.assertEqual(plan.fallback_reason, "query_planning_failed")

    def test_query_plan_normalizes_route_strategy_and_planner_mode_enums(self) -> None:
        plan = QueryPlan.from_dict(
            "recommend tofu",
            {
                "strategy": "combined",
                "planner_mode": "fast_rule",
                "constraints": {"needs_recipe_recommendation": True},
            },
        )

        self.assertIs(plan.strategy, SearchStrategy.COMBINED)
        self.assertIs(plan.planner_mode, QueryPlannerMode.FAST_RULE)
        self.assertEqual(plan.to_dict()["strategy"], "combined")
        self.assertEqual(plan.to_dict()["planner_mode"], "fast_rule")

    def test_scoring_uses_policy_structural_relationship_factor(self) -> None:
        from rag_modules.query_policy import get_query_policy
        from rag_modules.query_understanding.scoring import build_query_semantic_score_breakdown

        policy = get_query_policy()
        settings = QuerySemanticRuntimeSettings(relation_intensity_reference_ratio=1.0)

        score = build_query_semantic_score_breakdown(
            "relationship",
            settings=settings,
            relation_hits=[],
            structural_hits=["relationship"],
        )

        expected = min(
            1.0,
            policy.scoring.structural_relationship_factor
            / max(1.0, len(policy.lexicon.term_group("relation_markers"))),
        )
        self.assertEqual(score.lexical_relationship_intensity, expected)

        scoring_source = Path("rag_modules/query_understanding/scoring.py").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("structural_hit_count * 0.5", scoring_source)
        self.assertIn("policy.structural_relationship_factor", scoring_source)

    def test_calibrator_uses_policy_validation_labels(self) -> None:
        from rag_modules.query_policy import get_query_policy

        plan = QueryPlan.from_dict(
            "plain tofu",
            {"strategy": "combined", "graph_query_type": "entity_relation"},
        )
        self.planner._calibrator.calibrate(plan)

        label = get_query_policy().routing.validation_labels["strategy"]
        self.assertTrue(any(item.startswith(label + ":") for item in plan.validation_errors))

        calibration_source = Path(
            "rag_modules/query_understanding/planning/calibration.py"
        ).read_text(encoding="utf-8")
        self.assertNotIn("calibrated_strategy:", calibration_source)
        self.assertNotIn("calibrated_graph_query_type:", calibration_source)
        self.assertNotIn("calibrated_source_entities", calibration_source)
        self.assertIn('self.policy.validation_labels["strategy"]', calibration_source)

    def test_query_plan_normalizes_graph_query_type_enum(self) -> None:
        profile = QuerySemanticProfile.from_dict({"query_type": "multi_hop"})
        plan = QueryPlan.from_dict(
            "why does tofu work",
            {
                "graph_query_type": "path_finding",
                "semantic_profile": profile,
            },
        )

        self.assertIs(profile.query_type, GraphQueryType.MULTI_HOP)
        self.assertEqual(profile.to_dict()["query_type"], "multi_hop")
        self.assertIs(plan.graph_query_type, GraphQueryType.PATH_FINDING)
        self.assertEqual(plan.to_dict()["graph_query_type"], "path_finding")

    def test_query_plan_invalid_graph_query_type_falls_back_to_profile_enum(self) -> None:
        plan = QueryPlan.from_dict(
            "recommend tofu",
            {
                "graph_query_type": "typo",
                "semantic_profile": {"query_type": "entity_relation"},
            },
        )

        self.assertIs(plan.graph_query_type, GraphQueryType.ENTITY_RELATION)
        self.assertIn("invalid_graph_query_type:typo", plan.validation_errors)
        self.assertEqual(plan.to_dict()["graph_query_type"], "entity_relation")

    def test_query_plan_keeps_invalid_strategy_fallback_behavior(self) -> None:
        plan = QueryPlan.from_dict(
            "recommend tofu",
            {
                "strategy": "typo",
                "planner_mode": "llm",
                "constraints": {"needs_recipe_recommendation": True},
            },
        )

        self.assertIs(plan.strategy, SearchStrategy.COMBINED)
        self.assertIn("invalid_strategy:typo", plan.validation_errors)
        self.assertEqual(plan.to_dict()["strategy"], "combined")

    def test_constraint_extraction_uses_policy_rules(self) -> None:
        constraints = infer_query_constraints("20分钟内少油的鸡肉菜有哪些？")

        self.assertEqual(constraints["time"]["max_total_minutes"], 20)
        self.assertIn("少油", constraints["health_terms"])
        self.assertTrue(constraints["needs_recipe_recommendation"])


if __name__ == "__main__":
    unittest.main()

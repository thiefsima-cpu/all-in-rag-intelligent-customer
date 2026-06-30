from __future__ import annotations

import unittest

from rag_modules.contracts import (
    QueryPlan,
    QueryPlannerMode,
    QueryPlannerRuntimeSettings,
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

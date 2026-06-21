from __future__ import annotations

import unittest

from rag_modules.query_understanding import (
    QueryPlanner,
    infer_query_constraints,
    infer_query_semantic_profile,
)
from rag_modules.retrieval.runtime_profile import (
    QueryPlannerRuntimeSettings,
    QuerySemanticRuntimeSettings,
)


class _DummyCompletions:
    def create(self, **_: object) -> None:
        raise AssertionError("LLM planning should not be used in these unit tests.")


class _DummyChat:
    def __init__(self) -> None:
        self.completions = _DummyCompletions()


class _DummyLLM:
    def __init__(self) -> None:
        self.chat = _DummyChat()


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
        self.assertEqual(plan.strategy, "graph_rag")
        self.assertEqual(plan.graph_query_type, "multi_hop")
        self.assertIn(
            "水煮肉片",
            list(plan.entity_keywords) + list(plan.source_entities) + list(plan.target_entities),
        )

    def test_simple_recipe_query_prefers_hybrid(self) -> None:
        plan = self.planner.rule_based_plan("宫保鸡丁怎么做？")

        self.assertEqual(plan.strategy, "hybrid_traditional")
        self.assertEqual(plan.graph_query_type, "entity_relation")
        self.assertLess(plan.relationship_intensity, 0.7)

    def test_constraint_extraction_uses_policy_rules(self) -> None:
        constraints = infer_query_constraints("20分钟内少油的鸡肉菜有哪些？")

        self.assertEqual(constraints["time"]["max_total_minutes"], 20)
        self.assertIn("少油", constraints["health_terms"])
        self.assertTrue(constraints["needs_recipe_recommendation"])


if __name__ == "__main__":
    unittest.main()

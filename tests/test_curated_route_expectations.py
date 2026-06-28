from __future__ import annotations

import unittest

from rag_modules.contracts import (
    QueryPlannerRuntimeSettings,
    QuerySemanticRuntimeSettings,
)
from rag_modules.query_understanding import QueryPlanner
from scripts.eval_queries import load_eval_cases


class _DummyCompletions:
    def create(self, **_: object) -> None:
        raise AssertionError("LLM planning should not be used in these unit tests.")


class _DummyChat:
    def __init__(self) -> None:
        self.completions = _DummyCompletions()


class _DummyLLM:
    def __init__(self) -> None:
        self.chat = _DummyChat()


class CuratedRouteExpectationTests(unittest.TestCase):
    def test_rule_based_planner_matches_curated_strategy_expectations(self) -> None:
        planner = QueryPlanner(
            _DummyLLM(),
            settings=QueryPlannerRuntimeSettings(fast_rule_planning=True),
            semantic_settings=QuerySemanticRuntimeSettings(),
        )

        for case in load_eval_cases():
            if not case.expected_strategy:
                continue
            with self.subTest(query=case.query):
                plan = planner.rule_based_plan(case.query)
                self.assertEqual(plan.strategy, case.expected_strategy)
                if case.expected_strategy == "graph_rag":
                    self.assertGreaterEqual(plan.complexity, 0.7)
                    self.assertGreaterEqual(plan.relationship_intensity, 0.7)


if __name__ == "__main__":
    unittest.main()

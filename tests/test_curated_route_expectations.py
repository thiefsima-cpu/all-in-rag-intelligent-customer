from __future__ import annotations

import unittest

from rag_modules.contracts.query_settings import (
    QueryPlannerRuntimeSettings,
    QuerySemanticRuntimeSettings,
)
from rag_modules.query_understanding import QueryPlanner
from scripts.eval_queries import load_eval_cases
from tests.configuration_test_helpers import build_test_config


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
        config = build_test_config()
        planner = QueryPlanner(
            _DummyLLM(),
            settings=QueryPlannerRuntimeSettings.from_config(config),
            semantic_settings=QuerySemanticRuntimeSettings.from_config(config),
        )

        for case in load_eval_cases():
            expected_strategy = case.expectation.strategy
            if not expected_strategy:
                continue
            with self.subTest(query=case.query):
                plan = planner.rule_based_plan(case.query)
                self.assertEqual(plan.strategy, expected_strategy)
                if expected_strategy == "graph_rag":
                    self.assertGreaterEqual(plan.complexity, 0.7)
                    self.assertGreaterEqual(plan.relationship_intensity, 0.7)


if __name__ == "__main__":
    unittest.main()

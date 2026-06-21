from __future__ import annotations

import json
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

from rag_modules.query_understanding import QueryPlanner
from rag_modules.retrieval.runtime_profile import QueryPlannerRuntimeSettings


class _BlockingLLMClient:
    def __init__(self) -> None:
        self.calls = 0
        self._lock = threading.Lock()
        self.started = threading.Event()
        self.release = threading.Event()

    def create_completion(self, **kwargs):
        del kwargs
        with self._lock:
            self.calls += 1
        self.started.set()
        self.release.wait(timeout=2.0)
        payload = {
            "strategy": "hybrid_traditional",
            "graph_query_type": "subgraph",
            "complexity": 0.2,
            "relationship_intensity": 0.1,
        }
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(payload)))]
        )


class QueryPlannerConcurrencyTests(unittest.TestCase):
    def test_same_query_is_single_flight_and_returns_isolated_plans(self) -> None:
        client = _BlockingLLMClient()
        planner = QueryPlanner(
            client,
            settings=QueryPlannerRuntimeSettings(
                cache_size=8,
                fast_rule_planning=False,
            ),
        )
        planner.rule_based_plan("warm up tokenizer")

        with ThreadPoolExecutor(max_workers=2) as executor:
            first_future = executor.submit(planner.plan, "concurrent query")
            self.assertTrue(client.started.wait(timeout=1.0))
            second_future = executor.submit(planner.plan, "concurrent query")
            time.sleep(0.05)
            client.release.set()
            first = first_future.result(timeout=5.0)
            second = second_future.result(timeout=5.0)

        self.assertEqual(client.calls, 1)
        self.assertIsNot(first, second)
        self.assertFalse(first.used_cache)
        self.assertTrue(second.used_cache)

        second.validation_errors.append("caller-local")
        cached = planner.plan("concurrent query")

        self.assertTrue(cached.used_cache)
        self.assertNotIn("caller-local", cached.validation_errors)


if __name__ == "__main__":
    unittest.main()

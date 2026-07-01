from __future__ import annotations

import importlib.util
import unittest

import rag_modules.routing as routing


class IntelligentQueryRouterRetirementTests(unittest.TestCase):
    def test_router_adapter_is_not_exported_from_routing_package(self) -> None:
        self.assertNotIn("IntelligentQueryRouter", routing.__all__)
        self.assertNotIn("INTELLIGENT_QUERY_ROUTER_REMOVAL_VERSION", routing.__all__)

        with self.assertRaises(AttributeError):
            getattr(routing, "IntelligentQueryRouter")
        with self.assertRaises(AttributeError):
            getattr(routing, "INTELLIGENT_QUERY_ROUTER_REMOVAL_VERSION")

    def test_router_adapter_module_is_removed(self) -> None:
        self.assertIsNone(importlib.util.find_spec("rag_modules.routing.intelligent_query_router"))


if __name__ == "__main__":
    unittest.main()

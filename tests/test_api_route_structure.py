from __future__ import annotations

import ast
import importlib
import importlib.util
import unittest
from pathlib import Path


class ApiRouteStructureTests(unittest.TestCase):
    def test_api_routes_are_split_by_surface(self) -> None:
        for module_name in ("serving_routes", "build_routes", "operational_routes"):
            with self.subTest(module_name=module_name):
                spec = importlib.util.find_spec(f"rag_modules.interfaces.api.{module_name}")

                self.assertIsNotNone(spec)
                self.assertIsNotNone(spec.origin)
                self.assertTrue(Path(spec.origin).is_file())

    def test_routes_module_is_thin_compatibility_facade(self) -> None:
        routes = importlib.import_module("rag_modules.interfaces.api.routes")
        serving_routes = importlib.import_module("rag_modules.interfaces.api.serving_routes")
        build_routes = importlib.import_module("rag_modules.interfaces.api.build_routes")
        source = Path(routes.__file__).read_text(encoding="utf-8")
        tree = ast.parse(source, filename=routes.__file__)

        function_names = [
            node.name
            for node in tree.body
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
        ]

        self.assertEqual([], function_names)
        self.assertIs(routes.register_serving_routes, serving_routes.register_serving_routes)
        self.assertIs(routes.register_build_routes, build_routes.register_build_routes)
        self.assertEqual(
            {"register_build_routes", "register_serving_routes"},
            set(routes.__all__),
        )


if __name__ == "__main__":
    unittest.main()

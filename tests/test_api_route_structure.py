from __future__ import annotations

import ast
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

    def test_application_assembly_imports_route_owners_directly(self) -> None:
        spec = importlib.util.find_spec("rag_modules.interfaces.api.app")
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.origin)

        source = Path(spec.origin).read_text(encoding="utf-8")
        tree = ast.parse(source, filename=spec.origin)
        direct_imports = {
            (node.level, node.module, alias.name)
            for node in tree.body
            if isinstance(node, ast.ImportFrom)
            for alias in node.names
        }

        self.assertIn((1, "build_routes", "register_build_routes"), direct_imports)
        self.assertIn((1, "serving_routes", "register_serving_routes"), direct_imports)
        self.assertFalse(
            any(level == 1 and module == "routes" for level, module, _name in direct_imports)
        )


if __name__ == "__main__":
    unittest.main()

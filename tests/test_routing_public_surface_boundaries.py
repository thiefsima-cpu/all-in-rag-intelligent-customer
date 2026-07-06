from __future__ import annotations

import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAG_MODULES_DIR = ROOT / "rag_modules"


class RoutingPublicSurfaceBoundaryTests(unittest.TestCase):
    def test_internal_and_script_routing_use_route_resolution_contract(self) -> None:
        violations: list[str] = []

        for base_dir in (RAG_MODULES_DIR, ROOT / "scripts"):
            for path in base_dir.rglob("*.py"):
                rel = path.relative_to(ROOT)
                source = path.read_text(encoding="utf-8-sig")
                tree = ast.parse(source, filename=str(path))
                lines = source.splitlines()

                for node in ast.walk(tree):
                    if isinstance(node, ast.FunctionDef) and node.name == "route_query":
                        violations.append(f"{rel}:{node.lineno}: {lines[node.lineno - 1].strip()}")
                    elif isinstance(node, ast.Call):
                        func = node.func
                        if isinstance(func, ast.Attribute) and func.attr == "route_query":
                            violations.append(
                                f"{rel}:{node.lineno}: {lines[node.lineno - 1].strip()}"
                            )

        self.assertFalse(
            violations,
            "Found routing calls that bypass RouteResolution.route():\n" + "\n".join(violations),
        )

    def test_online_graph_route_requires_trace_capable_graph_retrieval(self) -> None:
        source = (RAG_MODULES_DIR / "routing" / "strategies" / "graph.py").read_text(
            encoding="utf-8-sig"
        )

        self.assertNotIn("hasattr", source)
        self.assertNotIn("graph_rag_evidence_search(", source)

    def test_online_runtime_does_not_use_dual_shape_retrieval_signatures(self) -> None:
        files = [
            RAG_MODULES_DIR / "retrieval" / "hybrid_executor.py",
            RAG_MODULES_DIR / "retrieval" / "hybrid_search_service.py",
            RAG_MODULES_DIR / "graph" / "rag_retrieval.py",
            RAG_MODULES_DIR / "graph" / "retrieval_runtime.py",
            RAG_MODULES_DIR / "routing" / "strategies" / "graph.py",
            RAG_MODULES_DIR / "routing" / "strategies" / "combined.py",
        ]
        source = "\n".join(path.read_text(encoding="utf-8-sig") for path in files)

        self.assertNotIn("request_or_query", source)
        self.assertNotIn("hasattr(", source)
        self.assertNotIn("graph_rag_evidence_search(", source)

    def test_combined_route_reports_control_cancellation_not_future_cancellation(self) -> None:
        source = (RAG_MODULES_DIR / "routing" / "strategies" / "combined.py").read_text(
            encoding="utf-8-sig"
        )

        self.assertIn("cancel_observed_branches", source)
        self.assertNotIn('"cancelled_branches"', source)

    def test_graph_retrieval_executor_exposes_trace_only_execution(self) -> None:
        source = (RAG_MODULES_DIR / "graph" / "retrieval_executor.py").read_text(
            encoding="utf-8-sig"
        )

        self.assertIn("def execute_with_trace", source)
        self.assertNotIn("def execute(self, request", source)


if __name__ == "__main__":
    unittest.main()

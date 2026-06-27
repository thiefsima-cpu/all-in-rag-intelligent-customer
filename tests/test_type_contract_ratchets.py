from __future__ import annotations

import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

NO_EXPLICIT_ANY_TARGETS = (
    ROOT / "rag_modules" / "app" / "provider_components" / "contracts.py",
    ROOT / "rag_modules" / "app" / "provider_components" / "query_understanding.py",
    ROOT / "rag_modules" / "app" / "provider_components" / "retrieval.py",
    ROOT / "rag_modules" / "interfaces" / "api" / "answer_models.py",
    ROOT / "rag_modules" / "interfaces" / "api" / "build_models.py",
    ROOT / "rag_modules" / "interfaces" / "api" / "diagnostics_models.py",
    ROOT / "rag_modules" / "routing" / "contracts.py",
    ROOT / "rag_modules" / "routing" / "execution_strategies.py",
    ROOT / "rag_modules" / "routing" / "search_orchestrator.py",
    ROOT / "rag_modules" / "routing" / "statistics.py",
)


class TypeContractRatchetTests(unittest.TestCase):
    def test_target_contract_modules_do_not_use_explicit_any(self) -> None:
        violations: list[str] = []

        for path in NO_EXPLICIT_ANY_TARGETS:
            source = path.read_text(encoding="utf-8-sig")
            tree = ast.parse(source, filename=str(path))
            lines = source.splitlines()
            for node in ast.walk(tree):
                if isinstance(node, ast.Name) and node.id == "Any":
                    rel = path.relative_to(ROOT)
                    violations.append(f"{rel}:{node.lineno}: {lines[node.lineno - 1].strip()}")

        self.assertFalse(
            violations,
            "Found explicit Any in the next strict type-contract island:\n" + "\n".join(violations),
        )


if __name__ == "__main__":
    unittest.main()

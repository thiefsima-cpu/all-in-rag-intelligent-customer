from __future__ import annotations

import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

NO_EXPLICIT_ANY_TARGETS = (
    ROOT / "rag_modules" / "app" / "providers" / "__init__.py",
    ROOT / "rag_modules" / "app" / "providers" / "build_pipeline.py",
    ROOT / "rag_modules" / "app" / "providers" / "contracts.py",
    ROOT / "rag_modules" / "app" / "providers" / "default.py",
    ROOT / "rag_modules" / "app" / "providers" / "generation.py",
    ROOT / "rag_modules" / "app" / "providers" / "infrastructure.py",
    ROOT / "rag_modules" / "app" / "providers" / "retrieval_runtime.py",
    ROOT / "rag_modules" / "app" / "providers" / "services.py",
    ROOT / "rag_modules" / "app" / "diagnostics.py",
    ROOT / "rag_modules" / "app" / "bootstrap_facade_contracts.py",
    ROOT / "rag_modules" / "app" / "bootstrap_facade_support.py",
    ROOT / "rag_modules" / "app" / "services" / "answer_models.py",
    ROOT / "rag_modules" / "app" / "services" / "answer_pipeline.py",
    ROOT / "rag_modules" / "app" / "services" / "answer_trace_assembler.py",
    ROOT / "rag_modules" / "app" / "services" / "answer_workflow.py",
    ROOT / "rag_modules" / "app" / "services" / "runtime_diagnostics_service.py",
    ROOT / "rag_modules" / "app" / "services" / "trace_adapters.py",
    ROOT / "rag_modules" / "query_policy" / "models.py",
    ROOT / "rag_modules" / "query_policy" / "loader.py",
    ROOT / "rag_modules" / "interfaces" / "api" / "answer_models.py",
    ROOT / "rag_modules" / "interfaces" / "api" / "build_models.py",
    ROOT / "rag_modules" / "interfaces" / "api" / "diagnostics_models.py",
    ROOT / "rag_modules" / "interfaces" / "api" / "services" / "base.py",
    ROOT / "rag_modules" / "interfaces" / "api" / "services" / "build.py",
    ROOT / "rag_modules" / "interfaces" / "api" / "services" / "serving.py",
    ROOT / "rag_modules" / "interfaces" / "api" / "services" / "serving_readiness.py",
    ROOT / "rag_modules" / "graph" / "retrieval_components.py",
    ROOT / "rag_modules" / "graph" / "cache_stats.py",
    ROOT / "rag_modules" / "graph" / "retrieval_types.py",
    ROOT / "rag_modules" / "graph" / "retrieval_postprocess.py",
    ROOT / "rag_modules" / "graph" / "evidence_builder.py",
    ROOT / "rag_modules" / "graph" / "reasoning_strategy.py",
    ROOT / "rag_modules" / "graph" / "retrieval_runtime.py",
    ROOT / "rag_modules" / "observability" / "tracing.py",
    ROOT / "rag_modules" / "observability" / "tracing_event_builder.py",
    ROOT / "rag_modules" / "runtime" / "artifact_ports.py",
    ROOT / "rag_modules" / "runtime" / "generation_models.py",
    ROOT / "rag_modules" / "runtime" / "graph_models.py",
    ROOT / "rag_modules" / "runtime" / "retrieval_models.py",
    ROOT / "rag_modules" / "runtime" / "route_models.py",
    ROOT / "rag_modules" / "runtime" / "stats_adapters.py",
    ROOT / "rag_modules" / "runtime" / "stats_ports.py",
    ROOT / "rag_modules" / "runtime" / "trace_models.py",
    ROOT / "rag_modules" / "runtime" / "workflow_models.py",
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

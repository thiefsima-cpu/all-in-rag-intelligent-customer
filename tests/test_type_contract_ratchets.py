from __future__ import annotations

import ast
import fnmatch
import tomllib
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
    ROOT / "rag_modules" / "app" / "composition" / "contracts.py",
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
    ROOT / "rag_modules" / "interfaces" / "api" / "build_jobs" / "repository.py",
    ROOT / "rag_modules" / "graph" / "query_executor.py",
    ROOT / "rag_modules" / "graph" / "retrieval_executor.py",
    ROOT / "rag_modules" / "graph" / "retrieval_components.py",
    ROOT / "rag_modules" / "graph" / "cache_stats.py",
    ROOT / "rag_modules" / "graph" / "retrieval_types.py",
    ROOT / "rag_modules" / "graph" / "retrieval_postprocess.py",
    ROOT / "rag_modules" / "graph" / "evidence_builder.py",
    ROOT / "rag_modules" / "graph" / "reasoning_strategy.py",
    ROOT / "rag_modules" / "graph" / "retrieval_runtime.py",
    ROOT / "rag_modules" / "generation" / "execution" / "contracts.py",
    ROOT / "rag_modules" / "generation" / "execution" / "direct.py",
    ROOT / "rag_modules" / "generation" / "execution" / "timeouts.py",
    ROOT / "rag_modules" / "generation" / "execution" / "tracing.py",
    ROOT / "rag_modules" / "generation" / "execution" / "two_stage.py",
    ROOT / "rag_modules" / "retrieval" / "adapters" / "bm25_retriever.py",
    ROOT / "rag_modules" / "retrieval" / "adapters" / "constraint_retriever.py",
    ROOT / "rag_modules" / "retrieval" / "adapters" / "graph_kv_retriever.py",
    ROOT / "rag_modules" / "retrieval" / "adapters" / "neo4j_fallback_retriever.py",
    ROOT / "rag_modules" / "retrieval" / "adapters" / "vector_retriever.py",
    ROOT / "rag_modules" / "build_pipeline" / "graph_preparation" / "models.py",
    ROOT / "rag_modules" / "build_pipeline" / "graph_preparation" / "statistics.py",
    ROOT / "rag_modules" / "build_pipeline" / "graph_preparation" / "document_builder.py",
    ROOT / "rag_modules" / "build_pipeline" / "graph_preparation" / "loader.py",
    ROOT / "rag_modules" / "build_pipeline" / "graph_preparation" / "module.py",
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


def _module_name_for_target(path: Path) -> str:
    relative_path = path.relative_to(ROOT)
    module_path = relative_path.with_suffix("")
    module_parts = list(module_path.parts)
    if module_parts[-1] == "__init__":
        module_parts = module_parts[:-1]
    return ".".join(module_parts)


def _strict_mypy_modules() -> list[str]:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    overrides = pyproject["tool"]["mypy"]["overrides"]
    modules: list[str] = []

    for override in overrides:
        if not (
            override.get("check_untyped_defs")
            and override.get("disallow_untyped_defs")
            and override.get("warn_return_any")
        ):
            continue

        module_patterns = override["module"]
        if isinstance(module_patterns, str):
            modules.append(module_patterns)
        else:
            modules.extend(module_patterns)

    return modules


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

    def test_target_contract_modules_are_under_strict_mypy_override(self) -> None:
        strict_modules = _strict_mypy_modules()
        missing_modules: list[str] = []

        for path in NO_EXPLICIT_ANY_TARGETS:
            module_name = _module_name_for_target(path)
            if not any(
                fnmatch.fnmatchcase(module_name, strict_module) for strict_module in strict_modules
            ):
                missing_modules.append(module_name)

        self.assertFalse(
            missing_modules,
            "Found type-contract targets outside the strict mypy override:\n"
            + "\n".join(missing_modules),
        )


if __name__ == "__main__":
    unittest.main()

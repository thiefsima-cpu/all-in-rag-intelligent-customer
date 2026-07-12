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
    ROOT / "rag_modules" / "app" / "ports.py",
    ROOT / "rag_modules" / "app" / "composition" / "build_jobs.py",
    ROOT / "rag_modules" / "app" / "composition" / "contracts.py",
    ROOT / "rag_modules" / "app" / "composition" / "serving_runtime_factory.py",
    ROOT / "rag_modules" / "app" / "composition" / "system_composer.py",
    ROOT / "rag_modules" / "application" / "answering" / "answer_models.py",
    ROOT / "rag_modules" / "application" / "answering" / "answer_pipeline.py",
    ROOT / "rag_modules" / "application" / "answering" / "answer_trace_assembler.py",
    ROOT / "rag_modules" / "application" / "answering" / "answer_workflow.py",
    ROOT / "rag_modules" / "application" / "knowledge_base.py",
    ROOT / "rag_modules" / "app" / "services" / "runtime_diagnostics_service.py",
    ROOT / "rag_modules" / "query_policy" / "models.py",
    ROOT / "rag_modules" / "query_policy" / "loader.py",
    ROOT / "rag_modules" / "interfaces" / "api" / "answer_models.py",
    ROOT / "rag_modules" / "interfaces" / "api" / "build_models.py",
    ROOT / "rag_modules" / "interfaces" / "api" / "diagnostics_models.py",
    ROOT / "rag_modules" / "interfaces" / "api" / "services" / "base.py",
    ROOT / "rag_modules" / "interfaces" / "api" / "services" / "build.py",
    ROOT / "rag_modules" / "interfaces" / "api" / "services" / "serving.py",
    ROOT / "rag_modules" / "interfaces" / "api" / "services" / "serving_readiness.py",
    ROOT / "rag_modules" / "graph" / "query_intent.py",
    ROOT / "rag_modules" / "graph" / "query_executor.py",
    ROOT / "rag_modules" / "graph" / "rag_retrieval.py",
    ROOT / "rag_modules" / "graph" / "query_resolution.py",
    ROOT / "rag_modules" / "graph" / "retrieval_plan.py",
    ROOT / "rag_modules" / "graph" / "retrieval_executor.py",
    ROOT / "rag_modules" / "graph" / "retrieval_components.py",
    ROOT / "rag_modules" / "graph" / "cache_stats.py",
    ROOT / "rag_modules" / "graph" / "retrieval_types.py",
    ROOT / "rag_modules" / "graph" / "retrieval_postprocess.py",
    ROOT / "rag_modules" / "graph" / "evidence_builder.py",
    ROOT / "rag_modules" / "graph" / "reasoning_strategy.py",
    ROOT / "rag_modules" / "graph" / "retrieval_runtime.py",
    ROOT / "rag_modules" / "graph" / "ports.py",
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
    ROOT / "rag_modules" / "retrieval" / "hybrid_index_service.py",
    ROOT / "rag_modules" / "retrieval" / "hybrid_runtime.py",
    ROOT / "rag_modules" / "retrieval" / "hybrid_service.py",
    ROOT / "rag_modules" / "retrieval" / "ports.py",
    ROOT / "rag_modules" / "retrieval" / "runtime_profile" / "profile.py",
    ROOT / "rag_modules" / "build_pipeline" / "graph_preparation" / "models.py",
    ROOT / "rag_modules" / "build_pipeline" / "graph_preparation" / "statistics.py",
    ROOT / "rag_modules" / "build_pipeline" / "graph_preparation" / "document_builder.py",
    ROOT / "rag_modules" / "build_pipeline" / "graph_preparation" / "loader.py",
    ROOT / "rag_modules" / "build_pipeline" / "graph_preparation" / "module.py",
    ROOT / "rag_modules" / "build_pipeline" / "ports.py",
    ROOT / "rag_modules" / "observability" / "tracing.py",
    ROOT / "rag_modules" / "observability" / "tracing_event_builder.py",
    ROOT / "rag_modules" / "contracts" / "runtime" / "generation.py",
    ROOT / "rag_modules" / "contracts" / "runtime" / "graph.py",
    ROOT / "rag_modules" / "contracts" / "runtime" / "retrieval.py",
    ROOT / "rag_modules" / "contracts" / "runtime" / "routing.py",
    ROOT / "rag_modules" / "contracts" / "runtime" / "tracing.py",
    ROOT / "rag_modules" / "contracts" / "runtime" / "workflows.py",
    ROOT / "rag_modules" / "kernel" / "routing.py",
    ROOT / "rag_modules" / "runtime" / "artifact_adapters.py",
    ROOT / "rag_modules" / "runtime" / "artifact_ports.py",
    ROOT / "rag_modules" / "runtime" / "stats_adapters.py",
    ROOT / "rag_modules" / "runtime" / "stats_ports.py",
    ROOT / "rag_modules" / "routing" / "contracts.py",
    ROOT / "rag_modules" / "routing" / "execution_strategies.py",
    ROOT / "rag_modules" / "routing" / "search_orchestrator.py",
)

NO_EXPLICIT_ANY_PACKAGE_TARGETS = (ROOT / "rag_modules" / "query_policy" / "parsers",)

STRICT_PACKAGE_TARGETS = (
    ROOT / "rag_modules" / "domain",
    ROOT / "rag_modules" / "contracts",
    ROOT / "rag_modules" / "query_policy" / "parsers",
    ROOT / "rag_modules" / "runtime",
)

PROVIDER_TYPE_SURFACE_TARGETS = (
    ROOT / "rag_modules" / "app" / "providers" / "contracts.py",
    ROOT / "rag_modules" / "app" / "providers" / "default.py",
    ROOT / "rag_modules" / "app" / "providers" / "generation.py",
    ROOT / "rag_modules" / "app" / "providers" / "retrieval_runtime.py",
    ROOT / "rag_modules" / "app" / "providers" / "services.py",
)

PROVIDER_CONCRETE_TYPE_NAMES = frozenset(
    {
        "AnswerWorkflow",
        "GenerationWorkflowService",
        "GraphRAGRetrieval",
        "HybridRetrievalService",
        "KnowledgeBaseService",
        "QueryUnderstandingService",
        "RuntimeDiagnosticsService",
        "RuntimeShutdownService",
    }
)

GLOBAL_STRICT_RATCHET_FLAGS = (
    "check_untyped_defs",
    "no_implicit_optional",
    "warn_return_any",
    "warn_unused_ignores",
)

STRICT_OVERRIDE_REQUIRED_FLAGS = (
    "check_untyped_defs",
    "disallow_untyped_defs",
    "warn_return_any",
)


def _module_name_for_target(path: Path) -> str:
    relative_path = path.relative_to(ROOT)
    module_path = relative_path.with_suffix("")
    module_parts = list(module_path.parts)
    if module_parts[-1] == "__init__":
        module_parts = module_parts[:-1]
    return ".".join(module_parts)


def _python_files_under(path: Path) -> list[Path]:
    return sorted(
        module_path for module_path in path.rglob("*.py") if "__pycache__" not in module_path.parts
    )


def _mypy_config() -> dict:
    return tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["tool"]["mypy"]


def _enabled_mypy_flag(config: dict, override: dict, flag: str) -> bool:
    return override.get(flag, config.get(flag)) is True


def _strict_mypy_modules() -> list[str]:
    config = _mypy_config()
    overrides = config["overrides"]
    modules: list[str] = []

    for override in overrides:
        if not all(
            _enabled_mypy_flag(config, override, flag) for flag in STRICT_OVERRIDE_REQUIRED_FLAGS
        ):
            continue

        module_patterns = override["module"]
        if isinstance(module_patterns, str):
            modules.append(module_patterns)
        else:
            modules.extend(module_patterns)

    return modules


def _python_modules_under(path: Path) -> list[str]:
    return sorted(_module_name_for_target(module_path) for module_path in _python_files_under(path))


def _annotation_type_names(annotation: ast.AST | None) -> set[str]:
    if annotation is None:
        return set()
    names: set[str] = set()
    for node in ast.walk(annotation):
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
    return names


class TypeContractRatchetTests(unittest.TestCase):
    def test_core_strict_rules_are_global_mypy_baseline(self) -> None:
        config = _mypy_config()
        missing_flags = [
            flag for flag in GLOBAL_STRICT_RATCHET_FLAGS if config.get(flag) is not True
        ]

        self.assertFalse(
            missing_flags,
            "Found strict mypy rules still limited to override islands:\n"
            + "\n".join(missing_flags),
        )

    def test_strict_mypy_overrides_inherit_global_ratchets(self) -> None:
        config = _mypy_config()
        overrides = config["overrides"]
        redundant_flags: list[str] = []

        for override in overrides:
            if not all(
                _enabled_mypy_flag(config, override, flag)
                for flag in STRICT_OVERRIDE_REQUIRED_FLAGS
            ):
                continue

            module_patterns = override["module"]
            if isinstance(module_patterns, str):
                module_label = module_patterns
            else:
                module_label = ", ".join(module_patterns)

            redundant_flags.extend(
                f"{flag}: {module_label}"
                for flag in GLOBAL_STRICT_RATCHET_FLAGS
                if flag in override
            )

        self.assertFalse(
            redundant_flags,
            "Found strict mypy overrides redeclaring global ratchet rules:\n"
            + "\n".join(redundant_flags),
        )

    def test_target_contract_modules_do_not_use_explicit_any(self) -> None:
        violations: list[str] = []

        no_explicit_any_targets = list(NO_EXPLICIT_ANY_TARGETS)
        for package_path in NO_EXPLICIT_ANY_PACKAGE_TARGETS:
            no_explicit_any_targets.extend(_python_files_under(package_path))

        for path in no_explicit_any_targets:
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

    def test_strict_mypy_overrides_close_missing_imports(self) -> None:
        config = _mypy_config()
        overrides = config["overrides"]
        open_import_overrides: list[str] = []

        for override in overrides:
            if not all(
                _enabled_mypy_flag(config, override, flag)
                for flag in STRICT_OVERRIDE_REQUIRED_FLAGS
            ):
                continue
            if override.get("ignore_missing_imports") is False:
                continue

            module_patterns = override["module"]
            if isinstance(module_patterns, str):
                open_import_overrides.append(module_patterns)
            else:
                open_import_overrides.extend(module_patterns)

        self.assertFalse(
            open_import_overrides,
            "Found strict mypy overrides still inheriting global ignore_missing_imports:\n"
            + "\n".join(open_import_overrides),
        )

    def test_strict_package_targets_use_strict_mypy(self) -> None:
        strict_modules = _strict_mypy_modules()
        missing_modules: list[str] = []

        for package_path in STRICT_PACKAGE_TARGETS:
            for module_name in _python_modules_under(package_path):
                if not any(
                    fnmatch.fnmatchcase(module_name, strict_module)
                    for strict_module in strict_modules
                ):
                    missing_modules.append(module_name)

        self.assertFalse(
            missing_modules,
            "Found strict package target modules outside the strict mypy override:\n"
            + "\n".join(missing_modules),
        )

    def test_provider_type_surface_uses_ports_instead_of_concrete_subsystems(self) -> None:
        violations: list[str] = []

        for path in PROVIDER_TYPE_SURFACE_TARGETS:
            source = path.read_text(encoding="utf-8-sig")
            tree = ast.parse(source, filename=str(path))
            rel = path.relative_to(ROOT)
            lines = source.splitlines()

            for node in ast.walk(tree):
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                annotations = [
                    (node.returns, "return"),
                    *[(arg.annotation, f"argument {arg.arg}") for arg in node.args.args],
                    *[(arg.annotation, f"argument {arg.arg}") for arg in node.args.kwonlyargs],
                ]
                for annotation, label in annotations:
                    concrete_names = sorted(
                        PROVIDER_CONCRETE_TYPE_NAMES & _annotation_type_names(annotation)
                    )
                    if concrete_names:
                        violations.append(
                            f"{rel}:{node.lineno}: {node.name} {label} uses "
                            f"{', '.join(concrete_names)}: {lines[node.lineno - 1].strip()}"
                        )

        self.assertFalse(
            violations,
            "Provider method annotations must use protocol/port surfaces:\n"
            + "\n".join(violations),
        )


if __name__ == "__main__":
    unittest.main()

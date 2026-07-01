from __future__ import annotations

import ast
import importlib
import re
import sys
import tomllib
import unittest
from dataclasses import dataclass
from importlib.util import resolve_name
from pathlib import Path

from rag_modules.interfaces.api.versioning import API_PREFIX, API_VERSION
from rag_modules.public_surface_manifest import (
    EXTERNAL_PUBLIC_SURFACE,
    LEGACY_PUBLIC_SURFACE,
    LEGACY_PUBLIC_SURFACE_REMOVAL_VERSION,
    LEGACY_PUBLIC_SURFACE_SCAN_RULES,
    ROOT_PUBLIC_SURFACE,
    repo_root_facade_module_names,
    root_facade_module_names,
)

ROOT = Path(__file__).resolve().parents[1]
RAG_MODULES_DIR = ROOT / "rag_modules"
ALLOWED_ROOT_WRAPPERS = {f"{entry.module_name}.py" for entry in ROOT_PUBLIC_SURFACE}
PROHIBITED_ROOT_MODULES = root_facade_module_names()
PROHIBITED_REPO_ROOT_MODULES = repo_root_facade_module_names()
LEGACY_FACADE_MODULES = PROHIBITED_ROOT_MODULES | PROHIBITED_REPO_ROOT_MODULES
MIGRATED_ROOT_SHARED_MODULE_FILES = frozenset(
    {
        "artifact_documents.py",
        "artifact_json.py",
        "artifact_manifest.py",
        "artifact_manifest_store.py",
        "artifact_registry.py",
        "artifact_signatures.py",
        "artifacts.py",
        "query_constraints.py",
        "retrieval_post_processor.py",
        "semantic_schema.py",
        "tracing.py",
        "tracing_sinks.py",
    }
)
RETIRED_LEGACY_FACADE_MODULES = frozenset(
    {
        "config",
        "rag_modules.app.runtime_service_resolver",
        "rag_modules.app.services.question_answer_service",
        "rag_modules.generation.integration",
        "rag_modules.graph_data_preparation",
        "rag_modules.graph_indexing",
        "rag_modules.intelligent_query_router",
        "rag_modules.routing.intelligent_query_router",
        "rag_modules.retrieval.hybrid_facade",
    }
)
PROHIBITED_LEGACY_FACADE_MODULES = LEGACY_FACADE_MODULES | RETIRED_LEGACY_FACADE_MODULES
RETIRED_LATE_MIGRATION_COMPAT_EXPORTS = {
    "rag_modules.configuration.section_loaders": RAG_MODULES_DIR
    / "configuration"
    / "section_loaders.py",
    "rag_modules.configuration.settings": RAG_MODULES_DIR / "configuration" / "settings.py",
    "rag_modules.generation.client": RAG_MODULES_DIR / "generation" / "client.py",
    "rag_modules.generation.executor": RAG_MODULES_DIR / "generation" / "executor.py",
    "rag_modules.interfaces.api.models": RAG_MODULES_DIR / "interfaces" / "api" / "models.py",
    "rag_modules.interfaces.api.service": RAG_MODULES_DIR / "interfaces" / "api" / "service.py",
    "rag_modules.retrieval.bm25_retriever": RAG_MODULES_DIR / "retrieval" / "bm25_retriever.py",
    "rag_modules.retrieval.constraint_retriever": RAG_MODULES_DIR
    / "retrieval"
    / "constraint_retriever.py",
    "rag_modules.retrieval.graph_kv_retriever": RAG_MODULES_DIR
    / "retrieval"
    / "graph_kv_retriever.py",
    "rag_modules.retrieval.retrieval_contracts": RAG_MODULES_DIR
    / "retrieval"
    / "retrieval_contracts.py",
    "rag_modules.retrieval.runtime_settings": RAG_MODULES_DIR / "retrieval" / "runtime_settings.py",
    "rag_modules.retrieval.vector_retriever": RAG_MODULES_DIR / "retrieval" / "vector_retriever.py",
}
RETIRED_INTERNAL_COMPAT_SHELLS = {
    "rag_modules.app.composition.build_runtime_assembler": RAG_MODULES_DIR
    / "app"
    / "composition"
    / "build_runtime_assembler.py",
    "rag_modules.app.composition.serving_runtime_assembler": RAG_MODULES_DIR
    / "app"
    / "composition"
    / "serving_runtime_assembler.py",
    "rag_modules.app.runtime": RAG_MODULES_DIR / "app" / "runtime.py",
}
RETIRED_INTERNAL_COMPAT_NAMES = frozenset(
    {
        "BuildRuntimeAssembler",
        "ServingRuntimeAssembler",
        "provide_query_router",
    }
)
RETIRED_PROVIDER_COMPONENTS_PACKAGE = "rag_modules.app.provider_components"
RETIRED_PROVIDER_COMPONENTS_PATH = RAG_MODULES_DIR / "app" / "provider_components"
RETIRED_PROVIDER_COMPONENTS_MODULES = frozenset(
    {
        RETIRED_PROVIDER_COMPONENTS_PACKAGE,
        f"{RETIRED_PROVIDER_COMPONENTS_PACKAGE}.build_pipeline",
        f"{RETIRED_PROVIDER_COMPONENTS_PACKAGE}.contracts",
        f"{RETIRED_PROVIDER_COMPONENTS_PACKAGE}.diagnostics",
        f"{RETIRED_PROVIDER_COMPONENTS_PACKAGE}.generation",
        f"{RETIRED_PROVIDER_COMPONENTS_PACKAGE}.infrastructure",
        f"{RETIRED_PROVIDER_COMPONENTS_PACKAGE}.lifecycle",
        f"{RETIRED_PROVIDER_COMPONENTS_PACKAGE}.query_understanding",
        f"{RETIRED_PROVIDER_COMPONENTS_PACKAGE}.retrieval",
        f"{RETIRED_PROVIDER_COMPONENTS_PACKAGE}.runtime",
        f"{RETIRED_PROVIDER_COMPONENTS_PACKAGE}.services",
    }
)


@dataclass(frozen=True)
class AttributeBoundaryRule:
    path: Path
    prohibited_chains: frozenset[str]
    reason: str
    prohibited_prefixes: frozenset[str] = frozenset()


@dataclass(frozen=True)
class CallBoundaryRule:
    path: Path
    prohibited_names: frozenset[str]
    reason: str
    scope_name: str | None = None
    prohibited_name_patterns: tuple[re.Pattern[str], ...] = ()


@dataclass(frozen=True)
class DefinitionBoundaryRule:
    path: Path
    prohibited_names: frozenset[str]
    reason: str


@dataclass(frozen=True)
class DynamicLookupBoundaryRule:
    path: Path
    owner_names: frozenset[str]
    owner_chains: frozenset[str]
    reason: str


@dataclass(frozen=True)
class ImportBoundaryRule:
    path: Path
    prohibited_modules: frozenset[str]
    reason: str


APP_COMPOSITION_IMPORT_BOUNDARIES = (
    ImportBoundaryRule(
        path=RAG_MODULES_DIR / "app" / "runtime_view.py",
        prohibited_modules=frozenset(
            {
                "rag_modules.app.runtime_service_resolver",
                "rag_modules.app.services.question_answer_service",
            }
        ),
        reason="runtime view must not depend on retired runtime resolver or app service facades",
    ),
    ImportBoundaryRule(
        path=RAG_MODULES_DIR / "app" / "system.py",
        prohibited_modules=frozenset({"rag_modules.interfaces.cli_console"}),
        reason="API-only system facade must not depend on retired CLI modules",
    ),
    ImportBoundaryRule(
        path=RAG_MODULES_DIR / "app" / "composition" / "bootstrapper_composer.py",
        prohibited_modules=frozenset({RETIRED_PROVIDER_COMPONENTS_PACKAGE}),
        reason="composition roots must not depend on the retired provider_components package",
    ),
)

APP_COMPOSITION_CALL_BOUNDARIES = (
    CallBoundaryRule(
        path=RAG_MODULES_DIR / "app" / "runtime_view.py",
        prohibited_names=frozenset(
            {
                "QuestionAnswerService",
                "QuestionAnswerServiceResolver",
            }
        ),
        prohibited_name_patterns=(re.compile(r"^System.*View$"),),
        reason="runtime view facade must not assemble grouped views or legacy services inline",
    ),
    CallBoundaryRule(
        path=RAG_MODULES_DIR / "app" / "composition" / "runtime_manager.py",
        prohibited_names=frozenset({"compose", "getattr"}),
        reason="runtime manager constructor must not resolve lifecycle collaborators dynamically",
        scope_name="__init__",
    ),
    CallBoundaryRule(
        path=RAG_MODULES_DIR / "app" / "bootstrap.py",
        prohibited_names=frozenset(
            {
                "BuildBootstrapper",
                "BuildRuntimeExecutor",
                "BuildRuntimeFactory",
                "ServingBootstrapper",
                "ServingRuntimeFactory",
                "ServingRuntimePreparer",
                "SystemRuntimeBootstrapService",
            }
        ),
        reason="public bootstrapper facades must delegate runtime assembly instead of constructing it",
    ),
    CallBoundaryRule(
        path=RAG_MODULES_DIR / "app" / "system.py",
        prohibited_names=frozenset(
            {
                "InteractiveCliConsole",
                "merge_legacy_dir_names",
                "resolve_grouped_legacy_attribute",
            }
        ),
        reason="system facade must stay API-only and avoid retired legacy surface helpers",
    ),
)

APP_COMPOSITION_DEFINITION_BOUNDARIES = (
    DefinitionBoundaryRule(
        path=RAG_MODULES_DIR / "app" / "runtime_view.py",
        prohibited_names=frozenset(
            {
                "_resolve_data_module",
                "_resolve_index_module",
                "_resolve_neo4j_manager",
                "_resolve_query_tracer",
            }
        ),
        reason="runtime view facade must not grow private grouped-view resolver helpers",
    ),
)

APP_COMPOSITION_DYNAMIC_LOOKUP_BOUNDARIES = (
    DynamicLookupBoundaryRule(
        path=RAG_MODULES_DIR / "app" / "bootstrap.py",
        owner_names=frozenset(),
        owner_chains=frozenset(
            {"self.build_bootstrapper", "self.factory", "self.serving_bootstrapper"}
        ),
        reason="public bootstrapper facade must not inspect split bootstrappers dynamically",
    ),
    DynamicLookupBoundaryRule(
        path=RAG_MODULES_DIR / "app" / "system.py",
        owner_names=frozenset({"bootstrapper", "build_bootstrapper", "serving_bootstrapper"}),
        owner_chains=frozenset(),
        reason="system facade must not resolve bootstrapper surfaces inline",
    ),
    DynamicLookupBoundaryRule(
        path=RAG_MODULES_DIR / "app" / "composition" / "system_composer.py",
        owner_names=frozenset({"bootstrapper", "build_bootstrapper", "serving_bootstrapper"}),
        owner_chains=frozenset(),
        reason="system composition must use explicit provider-surface contracts, not ad hoc lookup",
    ),
)

APP_COMPOSITION_ATTRIBUTE_BOUNDARIES = (
    AttributeBoundaryRule(
        path=RAG_MODULES_DIR / "app" / "system.py",
        prohibited_chains=frozenset(
            {
                "services.answer_workflow",
                "self.facade_support.answer_question",
                "self.facade_support.answer_question_response",
                "self.interactive_service.run_interactive",
                "self.runtime_manager",
                "self.runtime_manager.build_knowledge_base",
                "self.runtime_manager.close",
                "self.runtime_manager.collect_startup_diagnostics",
                "self.runtime_manager.collect_system_stats",
                "self.runtime_manager.initialize_build_runtime",
                "self.runtime_manager.initialize_serving_runtime",
                "self.runtime_manager.initialize_system",
                "self.runtime_manager.is_build_initialized",
                "self.runtime_manager.is_initialized",
                "self.runtime_manager.is_serving_initialized",
                "self.runtime_manager.rebuild_knowledge_base",
                "self.runtime_manager.require_ready",
                "self.runtime_manager.runtime",
                "self.runtime_manager.runtime_view",
            }
        ),
        prohibited_prefixes=frozenset({"self.interactive_service"}),
        reason="system facade must access operations and runtime state through its public collaborators",
    ),
    AttributeBoundaryRule(
        path=RAG_MODULES_DIR / "app" / "composition" / "system_facade_support.py",
        prohibited_chains=frozenset(),
        prohibited_prefixes=frozenset({"self.runtime_manager."}),
        reason="facade support must not reach back into runtime manager internals",
    ),
    AttributeBoundaryRule(
        path=RAG_MODULES_DIR / "app" / "composition" / "system_answering_service.py",
        prohibited_chains=frozenset(
            {
                "self.facade_support.answer_question",
                "self.facade_support.answer_question_response",
            }
        ),
        prohibited_prefixes=frozenset({"self.runtime_manager."}),
        reason="answering service must not route back through facade support or runtime manager",
    ),
)


class PublicSurfaceBoundaryTests(unittest.TestCase):
    @staticmethod
    def _module_name_for_path(path: Path) -> str:
        rel = path.relative_to(RAG_MODULES_DIR)
        if rel.name == "__init__.py":
            parts = ("rag_modules", *rel.parts[:-1])
        else:
            parts = ("rag_modules", *rel.with_suffix("").parts)
        return ".".join(part for part in parts if part)

    @staticmethod
    def _package_name_for_path(path: Path) -> str:
        if path.is_relative_to(RAG_MODULES_DIR):
            rel = path.relative_to(RAG_MODULES_DIR)
            if rel.name == "__init__.py":
                parts = ("rag_modules", *rel.parts[:-1])
            else:
                parts = ("rag_modules", *rel.parts[:-1])
            return ".".join(part for part in parts if part)
        return path.stem

    @staticmethod
    def _legacy_facade_path(entry) -> Path:
        if entry.kind == "root_facade":
            return RAG_MODULES_DIR / f"{entry.module_name}.py"
        if entry.kind == "repo_root_facade":
            return ROOT / f"{entry.module_name}.py"
        raise AssertionError(f"Unsupported legacy facade kind: {entry.kind!r}")

    @staticmethod
    def _attribute_chain(node: ast.AST) -> tuple[str, ...]:
        parts: list[str] = []
        current = node
        while isinstance(current, ast.Attribute):
            parts.append(current.attr)
            current = current.value
        if not isinstance(current, ast.Name):
            return ()
        parts.append(current.id)
        return tuple(reversed(parts))

    @staticmethod
    def _version_tuple(version: str) -> tuple[int, int, int]:
        major, minor, patch = (int(part) for part in version.split("."))
        return major, minor, patch

    @classmethod
    def _resolve_import_from(cls, path: Path, node: ast.ImportFrom) -> str:
        module = node.module or ""
        if node.level == 0:
            return module
        relative_name = "." * node.level + module
        return resolve_name(relative_name, cls._package_name_for_path(path))

    @classmethod
    def _iter_resolved_imports(cls, path: Path):
        source = path.read_text(encoding="utf-8-sig")
        tree = ast.parse(source, filename=str(path))
        lines = source.splitlines()

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    yield node.lineno, lines[node.lineno - 1].strip(), alias.name, alias.name
            elif isinstance(node, ast.ImportFrom):
                module_name = cls._resolve_import_from(path, node)
                yield node.lineno, lines[node.lineno - 1].strip(), module_name, module_name
                for alias in node.names:
                    if alias.name != "*":
                        yield (
                            node.lineno,
                            lines[node.lineno - 1].strip(),
                            module_name,
                            f"{module_name}.{alias.name}",
                        )

    @staticmethod
    def _source_tree_and_lines(path: Path) -> tuple[ast.Module, list[str]]:
        source = path.read_text(encoding="utf-8-sig")
        return ast.parse(source, filename=str(path)), source.splitlines()

    @classmethod
    def _nodes_in_scope(cls, tree: ast.Module, scope_name: str | None):
        if scope_name is None:
            yield from ast.walk(tree)
            return
        for node in ast.walk(tree):
            if (
                isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name == scope_name
            ):
                yield from ast.walk(node)
                return

    @staticmethod
    def _call_name(node: ast.Call) -> str | None:
        if isinstance(node.func, ast.Name):
            return node.func.id
        if isinstance(node.func, ast.Attribute):
            return node.func.attr
        return None

    @staticmethod
    def _violation(path: Path, lineno: int, lines: list[str], reason: str) -> str:
        rel = path.relative_to(ROOT)
        return f"{rel}:{lineno}: {lines[lineno - 1].strip()} ({reason})"

    @classmethod
    def _collect_import_boundary_violations(cls, rule: ImportBoundaryRule) -> list[str]:
        tree, lines = cls._source_tree_and_lines(rule.path)
        violations: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_names = {alias.name for alias in node.names}
            elif isinstance(node, ast.ImportFrom):
                module_name = cls._resolve_import_from(rule.path, node)
                imported_names = {module_name}
                imported_names.update(
                    f"{module_name}.{alias.name}" for alias in node.names if alias.name != "*"
                )
            else:
                continue
            if any(
                cls._module_matches(name, set(rule.prohibited_modules)) for name in imported_names
            ):
                violations.append(cls._violation(rule.path, node.lineno, lines, rule.reason))
        return violations

    @classmethod
    def _collect_call_boundary_violations(cls, rule: CallBoundaryRule) -> list[str]:
        tree, lines = cls._source_tree_and_lines(rule.path)
        violations: list[str] = []
        for node in cls._nodes_in_scope(tree, rule.scope_name):
            if not isinstance(node, ast.Call):
                continue
            call_name = cls._call_name(node)
            if call_name is None:
                continue
            if call_name in rule.prohibited_names or any(
                pattern.match(call_name) for pattern in rule.prohibited_name_patterns
            ):
                violations.append(cls._violation(rule.path, node.lineno, lines, rule.reason))
        return violations

    @classmethod
    def _collect_definition_boundary_violations(cls, rule: DefinitionBoundaryRule) -> list[str]:
        tree, lines = cls._source_tree_and_lines(rule.path)
        violations: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                if node.name in rule.prohibited_names:
                    violations.append(cls._violation(rule.path, node.lineno, lines, rule.reason))
        return violations

    @classmethod
    def _collect_dynamic_lookup_boundary_violations(
        cls,
        rule: DynamicLookupBoundaryRule,
    ) -> list[str]:
        tree, lines = cls._source_tree_and_lines(rule.path)
        violations: list[str] = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if not isinstance(node.func, ast.Name) or node.func.id != "getattr":
                continue
            if not node.args:
                continue
            owner = node.args[0]
            owner_name = owner.id if isinstance(owner, ast.Name) else ""
            owner_chain = ".".join(cls._attribute_chain(owner))
            if owner_name in rule.owner_names or owner_chain in rule.owner_chains:
                violations.append(cls._violation(rule.path, node.lineno, lines, rule.reason))
        return violations

    @classmethod
    def _collect_attribute_boundary_violations(cls, rule: AttributeBoundaryRule) -> list[str]:
        tree, lines = cls._source_tree_and_lines(rule.path)
        violations: list[str] = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Attribute):
                continue
            chain = ".".join(cls._attribute_chain(node))
            if chain in rule.prohibited_chains or any(
                chain.startswith(prefix) for prefix in rule.prohibited_prefixes
            ):
                violations.append(cls._violation(rule.path, node.lineno, lines, rule.reason))
        return violations

    @staticmethod
    def _module_matches(module_name: str, prohibited: set[str]) -> bool:
        return any(
            module_name == prohibited_name or module_name.startswith(f"{prohibited_name}.")
            for prohibited_name in prohibited
        )

    def test_migrated_shared_modules_are_not_at_rag_modules_root(self) -> None:
        remaining = {
            path.name
            for path in RAG_MODULES_DIR.glob("*.py")
            if path.name in MIGRATED_ROOT_SHARED_MODULE_FILES
        }

        self.assertEqual(set(), remaining)

    def test_internal_modules_do_not_depend_on_compat_or_root_facades(self) -> None:
        violations: list[str] = []

        for path in RAG_MODULES_DIR.rglob("*.py"):
            rel = path.relative_to(RAG_MODULES_DIR)
            if "__pycache__" in rel.parts:
                continue
            if len(rel.parts) == 1 and rel.name in ALLOWED_ROOT_WRAPPERS:
                continue

            source = path.read_text(encoding="utf-8-sig")
            tree = ast.parse(source, filename=str(path))
            lines = source.splitlines()

            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name in PROHIBITED_LEGACY_FACADE_MODULES or alias.name.startswith(
                            "rag_modules.compat"
                        ):
                            violations.append(
                                f"{rel}:{node.lineno}: {lines[node.lineno - 1].strip()}"
                            )
                elif isinstance(node, ast.ImportFrom):
                    module_name = self._resolve_import_from(path, node)
                    imported_names = {module_name}
                    imported_names.update(
                        f"{module_name}.{alias.name}" for alias in node.names if alias.name != "*"
                    )
                    if module_name.startswith("rag_modules.compat") or (
                        imported_names & PROHIBITED_LEGACY_FACADE_MODULES
                    ):
                        violations.append(f"{rel}:{node.lineno}: {lines[node.lineno - 1].strip()}")

        self.assertFalse(
            violations,
            "Found internal imports that still depend on compat/root facades:\n"
            + "\n".join(violations),
        )

    def test_scripts_do_not_import_repo_root_config_facade(self) -> None:
        violations: list[str] = []

        for path in (ROOT / "scripts").rglob("*.py"):
            rel = path.relative_to(ROOT)
            source = path.read_text(encoding="utf-8-sig")
            tree = ast.parse(source, filename=str(path))
            lines = source.splitlines()

            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module == "config":
                    violations.append(f"{rel}:{node.lineno}: {lines[node.lineno - 1].strip()}")
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name == "config":
                            violations.append(
                                f"{rel}:{node.lineno}: {lines[node.lineno - 1].strip()}"
                            )

        self.assertFalse(
            violations,
            "Found scripts importing repo-root configuration facades:\n" + "\n".join(violations),
        )

    def test_scripts_and_non_compat_tests_do_not_import_remaining_legacy_facades(self) -> None:
        violations: list[str] = []
        allowed_test_files = {
            ROOT / "tests" / "test_public_surface_boundaries.py",
        }

        for base_dir in (ROOT / "scripts", ROOT / "tests"):
            for path in base_dir.rglob("*.py"):
                if path in allowed_test_files:
                    continue
                rel = path.relative_to(ROOT)
                source = path.read_text(encoding="utf-8-sig")
                tree = ast.parse(source, filename=str(path))
                lines = source.splitlines()

                for node in ast.walk(tree):
                    if isinstance(node, ast.ImportFrom):
                        module_name = self._resolve_import_from(path, node)
                        imported_names = {module_name}
                        imported_names.update(
                            f"{module_name}.{alias.name}"
                            for alias in node.names
                            if alias.name != "*"
                        )
                        if imported_names & PROHIBITED_LEGACY_FACADE_MODULES:
                            violations.append(
                                f"{rel}:{node.lineno}: {lines[node.lineno - 1].strip()}"
                            )
                    elif isinstance(node, ast.Import):
                        for alias in node.names:
                            if alias.name in PROHIBITED_LEGACY_FACADE_MODULES:
                                violations.append(
                                    f"{rel}:{node.lineno}: {lines[node.lineno - 1].strip()}"
                                )

        self.assertFalse(
            violations,
            "Found scripts/tests importing remaining legacy facades outside compatibility checks:\n"
            + "\n".join(violations),
        )

    def test_scripts_and_non_compat_tests_do_not_import_runtime_models_facade(self) -> None:
        violations: list[str] = []
        allowed_test_files = {
            ROOT / "tests" / "test_public_surface_boundaries.py",
        }

        for base_dir in (ROOT / "scripts", ROOT / "tests"):
            for path in base_dir.rglob("*.py"):
                if path in allowed_test_files:
                    continue
                rel = path.relative_to(ROOT)
                source = path.read_text(encoding="utf-8-sig")
                tree = ast.parse(source, filename=str(path))
                lines = source.splitlines()

                for node in ast.walk(tree):
                    if (
                        isinstance(node, ast.ImportFrom)
                        and node.module == "rag_modules.runtime_models"
                    ):
                        violations.append(f"{rel}:{node.lineno}: {lines[node.lineno - 1].strip()}")
                    elif isinstance(node, ast.Import):
                        for alias in node.names:
                            if alias.name == "rag_modules.runtime_models":
                                violations.append(
                                    f"{rel}:{node.lineno}: {lines[node.lineno - 1].strip()}"
                                )

        self.assertFalse(
            violations,
            "Found scripts/tests still importing the runtime_models facade:\n"
            + "\n".join(violations),
        )

    def test_contract_kernel_does_not_depend_on_runtime_or_feature_packages(self) -> None:
        contracts_dir = RAG_MODULES_DIR / "contracts"
        prohibited = {
            "rag_modules.app",
            "rag_modules.generation",
            "rag_modules.graph",
            "rag_modules.query_understanding",
            "rag_modules.retrieval",
            "rag_modules.routing",
            "rag_modules.runtime",
        }
        violations: list[str] = []

        if not contracts_dir.exists():
            violations.append("rag_modules/contracts package is missing")
        else:
            for path in contracts_dir.rglob("*.py"):
                rel = path.relative_to(ROOT)
                for lineno, line, module_name, _imported_name in self._iter_resolved_imports(path):
                    if self._module_matches(module_name, prohibited):
                        violations.append(f"{rel}:{lineno}: {line}")

        self.assertFalse(
            violations,
            "Contract kernel must not import runtime or feature packages:\n"
            + "\n".join(violations),
        )

    def test_runtime_models_do_not_depend_on_retrieval_or_query_understanding(self) -> None:
        prohibited = {
            "rag_modules.query_understanding",
            "rag_modules.retrieval",
        }
        violations: list[str] = []

        for path in (RAG_MODULES_DIR / "runtime").rglob("*.py"):
            rel = path.relative_to(ROOT)
            for lineno, line, module_name, _imported_name in self._iter_resolved_imports(path):
                if self._module_matches(module_name, prohibited):
                    violations.append(f"{rel}:{lineno}: {line}")

        self.assertFalse(
            violations,
            "Runtime contracts must depend on rag_modules.contracts instead of feature packages:\n"
            + "\n".join(violations),
        )

    def test_domain_shared_does_not_import_langchain(self) -> None:
        violations: list[str] = []

        for path in (RAG_MODULES_DIR / "domain" / "shared").rglob("*.py"):
            rel = path.relative_to(ROOT)
            for lineno, line, module_name, _imported_name in self._iter_resolved_imports(path):
                if module_name == "langchain_core" or module_name.startswith("langchain_core."):
                    violations.append(f"{rel}:{lineno}: {line}")

        self.assertFalse(
            violations,
            "Domain shared modules must stay free of LangChain dependencies:\n"
            + "\n".join(violations),
        )

    def test_domain_shared_does_not_import_contracts(self) -> None:
        violations: list[str] = []

        for path in (RAG_MODULES_DIR / "domain" / "shared").rglob("*.py"):
            rel = path.relative_to(ROOT)
            for lineno, line, module_name, _imported_name in self._iter_resolved_imports(path):
                if module_name == "rag_modules.contracts" or module_name.startswith(
                    "rag_modules.contracts."
                ):
                    violations.append(f"{rel}:{lineno}: {line}")

        self.assertFalse(
            violations,
            "Domain shared modules must stay free of contracts dependencies:\n"
            + "\n".join(violations),
        )

    def test_domain_shared_does_not_export_recipe_constraint_matcher(self) -> None:
        domain_shared = importlib.import_module("rag_modules.domain.shared")

        self.assertFalse(hasattr(domain_shared, "RecipeConstraintMatcher"))
        self.assertNotIn("RecipeConstraintMatcher", getattr(domain_shared, "__all__", ()))

    def test_recipe_constraint_matcher_is_not_imported_from_domain_shared(self) -> None:
        violations: list[str] = []
        old_matcher_import = "rag_modules.domain.shared.query_constraints.RecipeConstraintMatcher"

        for base_dir in (RAG_MODULES_DIR, ROOT / "scripts", ROOT / "tests"):
            for path in base_dir.rglob("*.py"):
                rel = path.relative_to(ROOT)
                if "__pycache__" in rel.parts:
                    continue
                if path == ROOT / "tests" / "test_public_surface_boundaries.py":
                    continue
                for lineno, line, _module_name, imported_name in self._iter_resolved_imports(path):
                    if imported_name == old_matcher_import:
                        violations.append(f"{rel}:{lineno}: {line}")

        self.assertFalse(
            violations,
            "RecipeConstraintMatcher must be imported from rag_modules.retrieval.evidence:\n"
            + "\n".join(violations),
        )

    def test_query_understanding_does_not_depend_on_retrieval_package(self) -> None:
        violations: list[str] = []

        for path in (RAG_MODULES_DIR / "query_understanding").rglob("*.py"):
            rel = path.relative_to(ROOT)
            for lineno, line, module_name, _imported_name in self._iter_resolved_imports(path):
                if self._module_matches(module_name, {"rag_modules.retrieval"}):
                    violations.append(f"{rel}:{lineno}: {line}")

        self.assertFalse(
            violations,
            "Query-understanding must not import retrieval runtime/profile packages:\n"
            + "\n".join(violations),
        )

    def test_repository_uses_contract_kernel_for_shared_dtos(self) -> None:
        violations: list[str] = []
        prohibited_old_contract_modules = {"rag_modules.retrieval.contracts"}
        prohibited_query_exports = {
            "rag_modules.query_understanding.QueryPlan",
            "rag_modules.query_understanding.QuerySemanticProfile",
        }

        for base_dir in (RAG_MODULES_DIR, ROOT / "scripts", ROOT / "tests"):
            for path in base_dir.rglob("*.py"):
                rel = path.relative_to(ROOT)
                if "__pycache__" in rel.parts:
                    continue
                for lineno, line, module_name, imported_name in self._iter_resolved_imports(path):
                    if self._module_matches(module_name, prohibited_old_contract_modules):
                        violations.append(f"{rel}:{lineno}: {line}")
                    elif imported_name in prohibited_query_exports:
                        violations.append(f"{rel}:{lineno}: {line}")

        self.assertFalse(
            violations,
            "Shared DTOs/settings must be imported from rag_modules.contracts:\n"
            + "\n".join(violations),
        )

    def test_scripts_and_non_compat_tests_do_not_import_retired_query_facades(self) -> None:
        violations: list[str] = []
        retired_modules = {
            "rag_modules.query_plan",
            "rag_modules.query_semantics",
            "rag_modules.compat.query_plan",
            "rag_modules.compat.query_semantics",
        }
        allowed_test_files = {
            ROOT / "tests" / "test_public_surface_boundaries.py",
        }

        for base_dir in (ROOT / "scripts", ROOT / "tests"):
            for path in base_dir.rglob("*.py"):
                if path in allowed_test_files:
                    continue
                rel = path.relative_to(ROOT)
                source = path.read_text(encoding="utf-8-sig")
                tree = ast.parse(source, filename=str(path))
                lines = source.splitlines()

                for node in ast.walk(tree):
                    if isinstance(node, ast.ImportFrom) and node.module in retired_modules:
                        violations.append(f"{rel}:{node.lineno}: {lines[node.lineno - 1].strip()}")
                    elif isinstance(node, ast.Import):
                        for alias in node.names:
                            if alias.name in retired_modules:
                                violations.append(
                                    f"{rel}:{node.lineno}: {lines[node.lineno - 1].strip()}"
                                )

        self.assertFalse(
            violations,
            "Found scripts/tests still importing retired query facades:\n" + "\n".join(violations),
        )

    def test_unversioned_query_policy_resources_and_helpers_are_retired(self) -> None:
        policy_dir = RAG_MODULES_DIR / "query_policy"

        self.assertFalse((policy_dir / "defaults.json").exists())
        self.assertFalse((policy_dir / "planner_prompt.txt").exists())

        package_source = (policy_dir / "__init__.py").read_text(encoding="utf-8")
        loader_source = (policy_dir / "loader.py").read_text(encoding="utf-8")
        for retired_name in ("get_planner_prompt_template", "flatten_term_groups"):
            with self.subTest(retired_name=retired_name):
                self.assertNotIn(retired_name, package_source)
                self.assertNotIn(retired_name, loader_source)
        self.assertNotIn("class QueryPolicy", loader_source)

    def test_retirement_plan_document_states_current_policy(self) -> None:
        plan_path = ROOT / "docs" / "public_surface_retirement_plan.md"
        self.assertTrue(plan_path.exists())
        content = plan_path.read_text(encoding="utf-8")

        for heading in (
            "## Current Policy",
            "## Canonical Packages",
            "## Legacy Bridge Status",
            "## Compatibility Closure",
            "## Scan Rules",
            "## Internal Freeze Rule",
            "## Retired Facade Rule",
            "## Retired Facade History",
            "## 0.2.0 Compatibility Note",
        ):
            self.assertIn(heading, content)
        self.assertNotIn("E:/ai-project/all-in-rag/code/C9/", content)
        self.assertIn("public_surface_manifest.py", content)
        self.assertIn("canonical imports", content)
        self.assertIn(LEGACY_PUBLIC_SURFACE_REMOVAL_VERSION, content)
        self.assertIn("internal_dependency_guard", content)
        self.assertIn("thin_wrapper_guard", content)
        self.assertIn("No legacy bridge remains registered", content)
        for expected in (
            "config.py",
            "rag_modules.graph_data_preparation",
            "rag_modules.graph_indexing",
            "rag_modules.intelligent_query_router",
            "rag_modules.configuration",
            "rag_modules.graph.data_preparation",
            "rag_modules.graph.indexing",
            "rag_modules.routing.RoutingWorkflowService",
            "retired in favor of",
            "late-migration compatibility exports",
            "rag_modules.interfaces.api.models",
            "rag_modules.interfaces.api.services",
            "rag_modules.generation.clients",
            "rag_modules.generation.execution",
            "rag_modules.contracts",
            "rag_modules.retrieval.runtime_profile",
            "rag_modules.app.runtime",
            "rag_modules.app.composition.build_runtime_assembler",
            "rag_modules.app.composition.serving_runtime_assembler",
            "provide_query_router",
            "rag_modules.app.provider_components",
            "rag_modules.app.providers",
            "ServingRuntimeRefreshService",
            "ServingRuntimeLifecycleService",
            "rag_modules.compat.*",
            "contract kernel",
            "must not recreate",
            "will fail instead of forwarding",
        ):
            self.assertIn(expected, content)

    def test_version_governance_distinguishes_package_api_and_compat_versions(self) -> None:
        with (ROOT / "pyproject.toml").open("rb") as file:
            package_version = tomllib.load(file)["project"]["version"]
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        policy = (ROOT / "docs" / "public_surface_retirement_plan.md").read_text(encoding="utf-8")
        normalized_readme = " ".join(readme.split())
        normalized_policy = " ".join(policy.split())

        for expected in (
            "## Version Governance",
            f"Package version: `{package_version}`",
            f"API version: `{API_VERSION}`",
            f"API prefix: `{API_PREFIX}`",
            f"Compatibility removal version: `{LEGACY_PUBLIC_SURFACE_REMOVAL_VERSION}`",
            "Package releases can keep the same API version",
            "Compatibility removals must name their version axis",
        ):
            self.assertIn(expected, normalized_readme)

        for expected in (
            "## Version Governance",
            "`pyproject.toml`",
            "`API_VERSION`",
            "`LEGACY_PUBLIC_SURFACE_REMOVAL_VERSION`",
            "package version, API version, and compatibility removal version are not interchangeable",
        ):
            self.assertIn(expected, normalized_policy)

    def test_completed_package_retirement_milestones_do_not_exceed_package_version(self) -> None:
        with (ROOT / "pyproject.toml").open("rb") as file:
            package_version = tomllib.load(file)["project"]["version"]
        package_version_tuple = self._version_tuple(package_version)
        policy = (ROOT / "docs" / "public_surface_retirement_plan.md").read_text(encoding="utf-8")
        package_removal_versions = {
            LEGACY_PUBLIC_SURFACE_REMOVAL_VERSION,
            *re.findall(
                r"\| [^|\n]+ \| [^|\n]+ \| [^|\n]+ \| package version `([^`]+)` \|", policy
            ),
        }

        self.assertTrue(package_removal_versions)
        for removal_version in sorted(package_removal_versions):
            with self.subTest(removal_version=removal_version):
                self.assertLessEqual(
                    self._version_tuple(removal_version),
                    package_version_tuple,
                    (
                        "Completed package compatibility removals must not be documented "
                        "beyond the current package version."
                    ),
                )

    def test_app_composition_maintenance_guide_documents_runtime_ownership(self) -> None:
        guide_path = ROOT / "docs" / "app_composition_maintenance_guide.md"
        self.assertTrue(guide_path.exists())
        guide = guide_path.read_text(encoding="utf-8")
        architecture = (ROOT / "docs" / "architecture.md").read_text(encoding="utf-8")
        policy = (ROOT / "docs" / "public_surface_retirement_plan.md").read_text(encoding="utf-8")

        for expected in (
            "Provider Map",
            "Factory Map",
            "Lifecycle Map",
            "InfrastructureProvider",
            "BuildPipelineProvider",
            "RetrievalRuntimeProvider",
            "ApplicationServiceProvider",
            "ServingRuntimeLifecycleService",
            "BuildRuntimeLifecycleService",
            "SystemRuntimeManager",
            "Do not reintroduce `rag_modules/app/provider_components`",
            "Do not reintroduce `ServingRuntimeRefreshService`",
        ):
            self.assertIn(expected, guide)

        self.assertIn("app_composition_maintenance_guide.md", architecture)
        self.assertIn("rag_modules.app.provider_components", policy)
        self.assertIn("ServingRuntimeRefreshService", policy)

    def test_active_compatibility_layers_are_retired_in_docs(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        policy = (ROOT / "docs" / "public_surface_retirement_plan.md").read_text(encoding="utf-8")

        self.assertIn("Use `/v1` for new API clients", readme)
        self.assertIn("Unversioned serving and build routes are retired", readme)
        self.assertNotIn("compatibility aliases during the migration window", readme)

        for expected in (
            "## Compatibility Closure",
            "No active compatibility layers remain",
            "unversioned HTTP API aliases are retired",
            "`rag_modules.routing.IntelligentQueryRouter` is retired",
            "`rag_modules.routing.RoutingWorkflowService`",
            "already-completed `0.2.0` import-facade retirement",
        ):
            self.assertIn(expected, policy)
        self.assertNotIn("remain active only for migration", policy)

    def test_api_routes_register_only_versioned_operational_paths(self) -> None:
        path = RAG_MODULES_DIR / "interfaces" / "api" / "routes.py"
        source = path.read_text(encoding="utf-8-sig")
        tree = ast.parse(source, filename=str(path))
        violations: list[str] = []

        def route_path(node: ast.AST) -> tuple[str, str] | None:
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                return ("unversioned", node.value)
            if not isinstance(node, ast.JoinedStr):
                return None
            has_api_prefix = any(
                isinstance(value, ast.FormattedValue)
                and isinstance(value.value, ast.Name)
                and value.value.id == "API_PREFIX"
                for value in node.values
            )
            if not has_api_prefix:
                return None
            suffix = "".join(
                value.value
                for value in node.values
                if isinstance(value, ast.Constant) and isinstance(value.value, str)
            )
            return ("versioned", suffix)

        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef):
                continue
            unversioned_paths: set[str] = set()
            versioned_paths: set[str] = set()
            for decorator in node.decorator_list:
                if not isinstance(decorator, ast.Call):
                    continue
                func = decorator.func
                if (
                    not isinstance(func, ast.Attribute)
                    or func.attr not in {"get", "post"}
                    or not isinstance(func.value, ast.Name)
                    or func.value.id != "app"
                    or not decorator.args
                ):
                    continue
                parsed_path = route_path(decorator.args[0])
                if parsed_path is None:
                    continue
                kind, parsed = parsed_path
                if kind == "versioned":
                    versioned_paths.add(parsed)
                else:
                    unversioned_paths.add(parsed)

            for unversioned_path in sorted(unversioned_paths):
                violations.append(f"{node.name}: {unversioned_path}")

        self.assertEqual(
            [],
            violations,
            "API route decorators must use canonical /v1 paths only.",
        )
        self.assertNotIn("_versioned_alias_route", source)

    def test_manifest_confirms_legacy_public_surface_is_retired(self) -> None:
        root_files = {
            path.stem
            for path in RAG_MODULES_DIR.glob("*.py")
            if path.name != "__init__.py"
            and (path.name in ALLOWED_ROOT_WRAPPERS or path.stem.startswith("graph_"))
        }
        manifest_root = {entry.module_name for entry in ROOT_PUBLIC_SURFACE}
        manifest_external = {entry.module_name for entry in EXTERNAL_PUBLIC_SURFACE}

        self.assertEqual(set(), root_files)
        self.assertEqual(set(), manifest_root)
        self.assertFalse((RAG_MODULES_DIR / "compat").exists())
        self.assertEqual(set(), manifest_external)
        self.assertEqual((), LEGACY_PUBLIC_SURFACE)
        self.assertEqual("0.2.0", LEGACY_PUBLIC_SURFACE_REMOVAL_VERSION)
        self.assertEqual(
            ("internal_dependency_guard", "thin_wrapper_guard"),
            LEGACY_PUBLIC_SURFACE_SCAN_RULES,
        )

    def test_remaining_legacy_facades_are_thin_registered_wrappers(self) -> None:
        violations: list[str] = []

        for entry in LEGACY_PUBLIC_SURFACE:
            path = self._legacy_facade_path(entry)
            rel = path.relative_to(ROOT)
            self.assertTrue(path.exists(), f"Missing legacy facade file for {entry.module_name}")
            source = path.read_text(encoding="utf-8-sig")
            tree = ast.parse(source, filename=str(path))
            imported_modules: set[str] = set()

            for index, node in enumerate(tree.body):
                if (
                    index == 0
                    and isinstance(node, ast.Expr)
                    and isinstance(node.value, ast.Constant)
                    and isinstance(node.value.value, str)
                ):
                    continue
                if isinstance(node, ast.ImportFrom):
                    module_name = self._resolve_import_from(path, node)
                    imported_modules.add(module_name)
                    if module_name == "__future__":
                        continue
                    if module_name != entry.canonical_module:
                        violations.append(
                            f"{rel}:{node.lineno}: imports {module_name!r}, expected {entry.canonical_module!r}"
                        )
                    if any(alias.name == "*" for alias in node.names):
                        violations.append(f"{rel}:{node.lineno}: star import is not a thin facade")
                    continue
                if isinstance(node, ast.Assign) and all(
                    isinstance(target, ast.Name) and target.id == "__all__"
                    for target in node.targets
                ):
                    continue
                violations.append(
                    f"{rel}:{node.lineno}: {source.splitlines()[node.lineno - 1].strip()}"
                )

            self.assertIn(
                entry.canonical_module,
                imported_modules,
                f"{entry.module_name} should import its canonical target {entry.canonical_module}",
            )

        self.assertFalse(
            violations,
            "Found legacy facades with local logic or unregistered dependencies:\n"
            + "\n".join(violations),
        )

    def test_retired_legacy_facade_files_are_removed(self) -> None:
        retired_paths = {
            ROOT / "config.py",
            RAG_MODULES_DIR / "app" / "runtime_service_resolver.py",
            RAG_MODULES_DIR / "app" / "services" / "question_answer_service.py",
            RAG_MODULES_DIR / "generation" / "integration.py",
            RAG_MODULES_DIR / "graph_data_preparation.py",
            RAG_MODULES_DIR / "graph_indexing.py",
            RAG_MODULES_DIR / "intelligent_query_router.py",
            RAG_MODULES_DIR / "routing" / "intelligent_query_router.py",
            RAG_MODULES_DIR / "retrieval" / "hybrid_facade.py",
        }

        self.assertEqual(
            set(),
            {path.relative_to(ROOT) for path in retired_paths if path.exists()},
        )

    def test_retired_facade_import_paths_fail_instead_of_forwarding(self) -> None:
        for module_name in sorted(RETIRED_LEGACY_FACADE_MODULES):
            with self.subTest(module_name=module_name):
                with self.assertRaises(ModuleNotFoundError):
                    importlib.import_module(module_name)

    def test_late_migration_compat_export_modules_are_removed(self) -> None:
        existing_paths = [
            path.relative_to(ROOT)
            for path in RETIRED_LATE_MIGRATION_COMPAT_EXPORTS.values()
            if path.exists()
        ]
        self.assertEqual(set(), set(existing_paths))

        importlib.invalidate_caches()
        for module_name in sorted(RETIRED_LATE_MIGRATION_COMPAT_EXPORTS):
            with self.subTest(module_name=module_name):
                sys.modules.pop(module_name, None)
                with self.assertRaises(ModuleNotFoundError):
                    importlib.import_module(module_name)

    def test_retired_internal_compat_shells_are_removed(self) -> None:
        existing_paths = [
            path.relative_to(ROOT)
            for path in RETIRED_INTERNAL_COMPAT_SHELLS.values()
            if path.exists()
        ]
        self.assertEqual(set(), set(existing_paths))

        importlib.invalidate_caches()
        for module_name in sorted(RETIRED_INTERNAL_COMPAT_SHELLS):
            with self.subTest(module_name=module_name):
                sys.modules.pop(module_name, None)
                with self.assertRaises(ModuleNotFoundError):
                    importlib.import_module(module_name)

    def test_retired_provider_components_package_is_removed(self) -> None:
        self.assertFalse(RETIRED_PROVIDER_COMPONENTS_PATH.exists())

        importlib.invalidate_caches()
        for module_name in sorted(RETIRED_PROVIDER_COMPONENTS_MODULES):
            with self.subTest(module_name=module_name):
                for cached_name in list(sys.modules):
                    if cached_name == RETIRED_PROVIDER_COMPONENTS_PACKAGE or cached_name.startswith(
                        f"{RETIRED_PROVIDER_COMPONENTS_PACKAGE}."
                    ):
                        sys.modules.pop(cached_name, None)
                with self.assertRaises(ModuleNotFoundError):
                    importlib.import_module(module_name)

    def test_code_does_not_import_retired_provider_components_package(self) -> None:
        allowed_files = {
            ROOT / "tests" / "test_public_surface_boundaries.py",
        }
        violations: list[str] = []

        for base_dir in (RAG_MODULES_DIR, ROOT / "scripts", ROOT / "tests"):
            for path in base_dir.rglob("*.py"):
                if path in allowed_files:
                    continue
                rel = path.relative_to(ROOT)
                source = path.read_text(encoding="utf-8-sig")
                tree = ast.parse(source, filename=str(path))
                lines = source.splitlines()

                for node in ast.walk(tree):
                    if isinstance(node, ast.ImportFrom):
                        module_name = self._resolve_import_from(path, node)
                        imported_names = {
                            module_name,
                            *(
                                f"{module_name}.{alias.name}"
                                for alias in node.names
                                if alias.name != "*"
                            ),
                        }
                        if any(
                            name == RETIRED_PROVIDER_COMPONENTS_PACKAGE
                            or name.startswith(f"{RETIRED_PROVIDER_COMPONENTS_PACKAGE}.")
                            for name in imported_names
                        ):
                            violations.append(
                                f"{rel}:{node.lineno}: {lines[node.lineno - 1].strip()}"
                            )
                    elif isinstance(node, ast.Import):
                        for alias in node.names:
                            if alias.name == RETIRED_PROVIDER_COMPONENTS_PACKAGE or (
                                alias.name.startswith(f"{RETIRED_PROVIDER_COMPONENTS_PACKAGE}.")
                            ):
                                violations.append(
                                    f"{rel}:{node.lineno}: {lines[node.lineno - 1].strip()}"
                                )

        self.assertFalse(
            violations,
            "Found imports of retired provider_components package:\n" + "\n".join(violations),
        )

    def test_internal_code_and_tests_do_not_reference_retired_internal_compat_names(
        self,
    ) -> None:
        allowed_files = {
            ROOT / "tests" / "test_public_surface_boundaries.py",
        }
        violations: list[str] = []

        for base_dir in (RAG_MODULES_DIR, ROOT / "scripts", ROOT / "tests"):
            for path in base_dir.rglob("*.py"):
                if path in allowed_files:
                    continue
                rel = path.relative_to(ROOT)
                source = path.read_text(encoding="utf-8-sig")
                tree = ast.parse(source, filename=str(path))
                lines = source.splitlines()

                for node in ast.walk(tree):
                    if isinstance(node, ast.ImportFrom):
                        module_name = self._resolve_import_from(path, node)
                        imported_names = {
                            f"{module_name}.{alias.name}"
                            for alias in node.names
                            if alias.name != "*"
                        }
                        if (
                            module_name in RETIRED_INTERNAL_COMPAT_SHELLS
                            or imported_names & set(RETIRED_INTERNAL_COMPAT_SHELLS)
                            or any(
                                alias.name in RETIRED_INTERNAL_COMPAT_NAMES for alias in node.names
                            )
                        ):
                            violations.append(
                                f"{rel}:{node.lineno}: {lines[node.lineno - 1].strip()}"
                            )
                    elif isinstance(node, ast.Import):
                        for alias in node.names:
                            if alias.name in RETIRED_INTERNAL_COMPAT_SHELLS:
                                violations.append(
                                    f"{rel}:{node.lineno}: {lines[node.lineno - 1].strip()}"
                                )
                    elif isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                        if node.name in RETIRED_INTERNAL_COMPAT_NAMES:
                            violations.append(
                                f"{rel}:{node.lineno}: {lines[node.lineno - 1].strip()}"
                            )

        self.assertFalse(
            violations,
            "Found references to retired internal compatibility shells:\n" + "\n".join(violations),
        )

    def test_internal_scripts_and_tests_use_canonical_imports_after_compat_retirement(
        self,
    ) -> None:
        retired_modules = set(RETIRED_LATE_MIGRATION_COMPAT_EXPORTS)
        allowed_files = {
            ROOT / "tests" / "test_public_surface_boundaries.py",
        }
        violations: list[str] = []

        for base_dir in (RAG_MODULES_DIR, ROOT / "scripts", ROOT / "tests"):
            for path in base_dir.rglob("*.py"):
                if path in allowed_files:
                    continue
                rel = path.relative_to(ROOT)
                source = path.read_text(encoding="utf-8-sig")
                tree = ast.parse(source, filename=str(path))
                lines = source.splitlines()

                for node in ast.walk(tree):
                    if isinstance(node, ast.ImportFrom):
                        module_name = self._resolve_import_from(path, node)
                        imported_names = {module_name}
                        imported_names.update(
                            f"{module_name}.{alias.name}"
                            for alias in node.names
                            if alias.name != "*"
                        )
                        if imported_names & retired_modules:
                            violations.append(
                                f"{rel}:{node.lineno}: {lines[node.lineno - 1].strip()}"
                            )
                    elif isinstance(node, ast.Import):
                        for alias in node.names:
                            if alias.name in retired_modules:
                                violations.append(
                                    f"{rel}:{node.lineno}: {lines[node.lineno - 1].strip()}"
                                )

        self.assertFalse(
            violations,
            "Found imports of retired late-migration compatibility exports:\n"
            + "\n".join(violations),
        )

    def test_runtime_metadata_does_not_advertise_retired_facade_modules(self) -> None:
        violations: list[str] = []

        for path in RAG_MODULES_DIR.rglob("*.py"):
            rel = path.relative_to(ROOT)
            source = path.read_text(encoding="utf-8-sig")
            tree = ast.parse(source, filename=str(path))
            lines = source.splitlines()

            for node in ast.walk(tree):
                if not isinstance(node, ast.Assign):
                    continue
                if not any(
                    isinstance(target, ast.Attribute) and target.attr == "__module__"
                    for target in node.targets
                ):
                    continue
                if (
                    isinstance(node.value, ast.Constant)
                    and node.value.value in RETIRED_LEGACY_FACADE_MODULES
                ):
                    violations.append(f"{rel}:{node.lineno}: {lines[node.lineno - 1].strip()}")

        self.assertFalse(
            violations,
            "Found runtime metadata still pointing at retired facade modules:\n"
            + "\n".join(violations),
        )

    def test_refactored_compat_modules_are_thin_exports(self) -> None:
        expected_imports = {
            RAG_MODULES_DIR / "infra" / "milvus_index_construction.py": {
                "rag_modules.infra.milvus",
            },
        }
        violations: list[str] = []

        for path, allowed_imports in expected_imports.items():
            source = path.read_text(encoding="utf-8-sig")
            tree = ast.parse(source, filename=str(path))
            rel = path.relative_to(ROOT)
            imported_modules: set[str] = set()

            for index, node in enumerate(tree.body):
                if (
                    index == 0
                    and isinstance(node, ast.Expr)
                    and isinstance(node.value, ast.Constant)
                    and isinstance(node.value.value, str)
                ):
                    continue
                if isinstance(node, ast.ImportFrom):
                    module_name = self._resolve_import_from(path, node)
                    imported_modules.add(module_name)
                    if module_name == "__future__":
                        continue
                    if module_name not in allowed_imports:
                        violations.append(
                            f"{rel}:{node.lineno}: imports {module_name!r}, expected one of {sorted(allowed_imports)!r}"
                        )
                    if any(alias.name == "*" for alias in node.names):
                        violations.append(f"{rel}:{node.lineno}: star import is not a thin export")
                    continue
                if isinstance(node, ast.Assign) and all(
                    isinstance(target, ast.Name) and target.id == "__all__"
                    for target in node.targets
                ):
                    continue
                violations.append(
                    f"{rel}:{node.lineno}: {source.splitlines()[node.lineno - 1].strip()}"
                )

            if not imported_modules & allowed_imports:
                violations.append(
                    f"{rel}: should import one canonical module from {sorted(allowed_imports)!r}"
                )

        self.assertFalse(
            violations,
            "Found refactored compatibility modules with local logic:\n" + "\n".join(violations),
        )

    def test_graph_database_driver_creation_stays_in_neo4j_infra_adapter(self) -> None:
        allowed_dir = RAG_MODULES_DIR / "infra" / "neo4j"
        violations: list[str] = []

        for base_dir in (RAG_MODULES_DIR, ROOT / "scripts"):
            for path in base_dir.rglob("*.py"):
                if "__pycache__" in path.parts or path.is_relative_to(allowed_dir):
                    continue

                source = path.read_text(encoding="utf-8-sig")
                tree = ast.parse(source, filename=str(path))
                lines = source.splitlines()
                rel = path.relative_to(ROOT)

                for node in ast.walk(tree):
                    if isinstance(node, ast.ImportFrom) and node.module == "neo4j":
                        if any(alias.name == "GraphDatabase" for alias in node.names):
                            violations.append(
                                f"{rel}:{node.lineno}: {lines[node.lineno - 1].strip()}"
                            )
                    elif isinstance(node, ast.Name) and node.id == "GraphDatabase":
                        violations.append(f"{rel}:{node.lineno}: {lines[node.lineno - 1].strip()}")
                    elif isinstance(node, ast.Attribute) and node.attr == "GraphDatabase":
                        violations.append(f"{rel}:{node.lineno}: {lines[node.lineno - 1].strip()}")

        self.assertFalse(
            violations,
            "Found direct GraphDatabase usage outside rag_modules.infra.neo4j:\n"
            + "\n".join(violations),
        )

    def test_neo4j_driver_library_imports_stay_in_neo4j_infra_adapter(self) -> None:
        allowed_dir = RAG_MODULES_DIR / "infra" / "neo4j"
        violations: list[str] = []

        for base_dir in (RAG_MODULES_DIR, ROOT / "scripts"):
            for path in base_dir.rglob("*.py"):
                if "__pycache__" in path.parts or path.is_relative_to(allowed_dir):
                    continue

                source = path.read_text(encoding="utf-8-sig")
                tree = ast.parse(source, filename=str(path))
                lines = source.splitlines()
                rel = path.relative_to(ROOT)

                for node in ast.walk(tree):
                    if isinstance(node, ast.ImportFrom):
                        module_name = self._resolve_import_from(path, node)
                        if module_name == "neo4j" or module_name.startswith("neo4j."):
                            violations.append(
                                f"{rel}:{node.lineno}: {lines[node.lineno - 1].strip()}"
                            )
                    elif isinstance(node, ast.Import):
                        for alias in node.names:
                            if alias.name == "neo4j" or alias.name.startswith("neo4j."):
                                violations.append(
                                    f"{rel}:{node.lineno}: {lines[node.lineno - 1].strip()}"
                                )

        self.assertFalse(
            violations,
            "Found Neo4j driver package imports outside rag_modules.infra.neo4j:\n"
            + "\n".join(violations),
        )

    def test_composer_modules_stay_under_composition_root_without_fixed_topology(self) -> None:
        composition_dir = RAG_MODULES_DIR / "app" / "composition"
        misplaced = [
            path.relative_to(ROOT)
            for path in (RAG_MODULES_DIR / "app").rglob("*composer.py")
            if not path.is_relative_to(composition_dir)
        ]

        self.assertFalse(
            misplaced,
            "Composer modules should live under rag_modules/app/composition without "
            f"pinning the exact composer file set:\n{misplaced}",
        )

    def test_runtime_model_dependencies_are_one_way(self) -> None:
        path = RAG_MODULES_DIR / "runtime" / "retrieval_models.py"
        tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
        imports = {
            self._resolve_import_from(path, node)
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
        }
        self.assertNotIn("rag_modules.runtime.workflow_models", imports)

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

    def test_internal_generation_assembly_uses_workflow_service_not_legacy_facade(self) -> None:
        violations: list[str] = []
        allowed_files = {
            RAG_MODULES_DIR / "generation_integration.py",
            RAG_MODULES_DIR / "compat" / "generation_integration.py",
        }

        for path in RAG_MODULES_DIR.rglob("*.py"):
            if path in allowed_files:
                continue
            rel = path.relative_to(ROOT)
            source = path.read_text(encoding="utf-8-sig")
            tree = ast.parse(source, filename=str(path))
            lines = source.splitlines()

            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    module_name = self._resolve_import_from(path, node)
                    if module_name == "rag_modules.generation.integration":
                        violations.append(f"{rel}:{node.lineno}: {lines[node.lineno - 1].strip()}")
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name == "rag_modules.generation.integration":
                            violations.append(
                                f"{rel}:{node.lineno}: {lines[node.lineno - 1].strip()}"
                            )

        self.assertFalse(
            violations,
            "Found internal imports of the legacy generation integration facade:\n"
            + "\n".join(violations),
        )

    def test_internal_generation_calls_are_context_native(self) -> None:
        prohibited_methods = {
            "generate_answer_from_evidence",
            "generate_answer_stream_from_evidence",
            "generate_answer_from_documents",
            "generate_answer_stream_from_documents",
            "generate_adaptive_answer",
            "generate_adaptive_answer_from_evidence",
            "generate_adaptive_answer_stream",
            "generate_adaptive_answer_stream_from_evidence",
            "compose_answer",
            "compose_answer_from_documents",
            "build_answer_plan",
            "build_answer_plan_from_documents",
        }
        allowed_files: set[Path] = set()
        violations: list[str] = []

        for base_dir in (RAG_MODULES_DIR, ROOT / "scripts"):
            for path in base_dir.rglob("*.py"):
                if path in allowed_files:
                    continue
                rel = path.relative_to(ROOT)
                source = path.read_text(encoding="utf-8-sig")
                tree = ast.parse(source, filename=str(path))
                lines = source.splitlines()

                for node in ast.walk(tree):
                    if isinstance(node, ast.Call):
                        func = node.func
                        if isinstance(func, ast.Attribute) and func.attr in prohibited_methods:
                            violations.append(
                                f"{rel}:{node.lineno}: {lines[node.lineno - 1].strip()}"
                            )

        self.assertFalse(
            violations,
            "Found generation calls that bypass AnswerContext-native APIs:\n"
            + "\n".join(violations),
        )

    def test_internal_query_understanding_imports_use_domain_service(self) -> None:
        allowed_files = {
            RAG_MODULES_DIR / "app" / "services" / "__init__.py",
        }
        violations: list[str] = []

        for path in RAG_MODULES_DIR.rglob("*.py"):
            if path in allowed_files:
                continue
            rel = path.relative_to(ROOT)
            source = path.read_text(encoding="utf-8-sig")
            tree = ast.parse(source, filename=str(path))
            lines = source.splitlines()

            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    module_name = self._resolve_import_from(path, node)
                    if module_name == "rag_modules.app.services.query_understanding_service":
                        violations.append(f"{rel}:{node.lineno}: {lines[node.lineno - 1].strip()}")
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name == "rag_modules.app.services.query_understanding_service":
                            violations.append(
                                f"{rel}:{node.lineno}: {lines[node.lineno - 1].strip()}"
                            )

        self.assertFalse(
            violations,
            "Found internal imports that still depend on the app-layer query-understanding facade:\n"
            + "\n".join(violations),
        )

    def test_internal_query_understanding_facade_is_removed(self) -> None:
        facade_path = RAG_MODULES_DIR / "app" / "services" / "query_understanding_service.py"

        self.assertFalse(
            facade_path.exists(),
            "app/services/query_understanding_service.py is a retired internal facade; "
            "use rag_modules.query_understanding.service instead.",
        )
        with self.assertRaises(ModuleNotFoundError):
            importlib.import_module("rag_modules.app.services.query_understanding_service")

    def test_internal_question_answering_imports_use_workflow_or_contracts(self) -> None:
        allowed_files: set[Path] = set()
        violations: list[str] = []

        for path in RAG_MODULES_DIR.rglob("*.py"):
            if path in allowed_files:
                continue
            rel = path.relative_to(ROOT)
            source = path.read_text(encoding="utf-8-sig")
            tree = ast.parse(source, filename=str(path))
            lines = source.splitlines()

            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    module_name = self._resolve_import_from(path, node)
                    if module_name == "rag_modules.app.services.question_answer_service":
                        violations.append(f"{rel}:{node.lineno}: {lines[node.lineno - 1].strip()}")
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name == "rag_modules.app.services.question_answer_service":
                            violations.append(
                                f"{rel}:{node.lineno}: {lines[node.lineno - 1].strip()}"
                            )

        self.assertFalse(
            violations,
            "Found internal imports that still depend on the app-layer question-answer facade:\n"
            + "\n".join(violations),
        )

    def test_runtime_view_facade_does_not_assemble_grouped_views_inline(self) -> None:
        violations: list[str] = []
        for rule in APP_COMPOSITION_IMPORT_BOUNDARIES:
            if rule.path.name == "runtime_view.py":
                violations.extend(self._collect_import_boundary_violations(rule))
        for rule in APP_COMPOSITION_DEFINITION_BOUNDARIES:
            if rule.path.name == "runtime_view.py":
                violations.extend(self._collect_definition_boundary_violations(rule))
        for rule in APP_COMPOSITION_CALL_BOUNDARIES:
            if rule.path.name == "runtime_view.py":
                violations.extend(self._collect_call_boundary_violations(rule))

        self.assertFalse(
            violations,
            "Found runtime-view assembly that should stay behind runtime view boundaries:\n"
            + "\n".join(violations),
        )

    def test_internal_and_script_answer_generation_do_not_route_through_compat_service(
        self,
    ) -> None:
        violations: list[str] = []

        for base_dir in (RAG_MODULES_DIR, ROOT / "scripts"):
            for path in base_dir.rglob("*.py"):
                rel = path.relative_to(ROOT)
                source = path.read_text(encoding="utf-8-sig")
                tree = ast.parse(source, filename=str(path))
                lines = source.splitlines()

                for node in ast.walk(tree):
                    if not isinstance(node, ast.Call):
                        continue
                    func = node.func
                    if not isinstance(func, ast.Attribute) or func.attr != "answer_question":
                        continue
                    owner = func.value
                    if isinstance(owner, ast.Attribute) and owner.attr == "question_answer_service":
                        violations.append(f"{rel}:{node.lineno}: {lines[node.lineno - 1].strip()}")

        self.assertFalse(
            violations,
            "Found answer-generation calls that still route through the compat question-answer service:\n"
            + "\n".join(violations),
        )

    def test_app_core_and_scripts_use_grouped_runtime_views(self) -> None:
        prohibited_accesses = {
            RAG_MODULES_DIR / "app" / "system.py": {
                "runtime.answer_workflow",
                "runtime.question_answer_service",
            },
            RAG_MODULES_DIR / "app" / "composition" / "runtime_manager.py": {
                "runtime.data_module",
                "runtime.index_module",
                "runtime.query_router",
                "runtime.retrieval_runtime_profile",
            },
            ROOT / "scripts" / "eval_queries.py": {
                "system.routing_workflow",
                "system.query_router",
            },
        }
        violations: list[str] = []

        for path, banned in prohibited_accesses.items():
            rel = path.relative_to(ROOT)
            source = path.read_text(encoding="utf-8-sig")
            tree = ast.parse(source, filename=str(path))
            lines = source.splitlines()

            for node in ast.walk(tree):
                if not isinstance(node, ast.Attribute):
                    continue
                chain = ".".join(self._attribute_chain(node))
                if chain in banned:
                    violations.append(f"{rel}:{node.lineno}: {lines[node.lineno - 1].strip()}")

        self.assertFalse(
            violations,
            "Found app-core/script access that bypasses grouped runtime views:\n"
            + "\n".join(violations),
        )

    def test_app_runtime_surfaces_do_not_use_legacy_flat_attribute_resolution(self) -> None:
        targets = {
            RAG_MODULES_DIR / "app" / "runtime_view.py",
            RAG_MODULES_DIR / "app" / "system.py",
            RAG_MODULES_DIR / "app" / "composition" / "system_facade_support.py",
        }
        violations: list[str] = []

        for path in targets:
            rel = path.relative_to(ROOT)
            source = path.read_text(encoding="utf-8-sig")
            tree = ast.parse(source, filename=str(path))

            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in {
                    "__getattr__",
                    "__dir__",
                    "resolve_legacy_attribute",
                    "legacy_dir",
                }:
                    violations.append(f"{rel}:{node.lineno}: def {node.name}(...)")
                elif isinstance(node, ast.ImportFrom):
                    module_name = self._resolve_import_from(path, node)
                    if module_name == "rag_modules.app.legacy_surface":
                        violations.append(f"{rel}:{node.lineno}: legacy_surface import")

        legacy_surface_path = RAG_MODULES_DIR / "app" / "legacy_surface.py"
        if legacy_surface_path.exists():
            violations.append(
                f"{legacy_surface_path.relative_to(ROOT)}: compatibility module still exists"
            )

        self.assertFalse(
            violations,
            "Found retired legacy flat runtime attribute support:\n" + "\n".join(violations),
        )

    def test_only_package_exports_use_module_getattr(self) -> None:
        violations: list[str] = []

        for path in RAG_MODULES_DIR.rglob("*.py"):
            rel = path.relative_to(ROOT)
            if "__pycache__" in rel.parts:
                continue
            source = path.read_text(encoding="utf-8-sig")
            tree = ast.parse(source, filename=str(path))

            for node in ast.walk(tree):
                if (
                    isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and node.name == "__getattr__"
                    and path.name != "__init__.py"
                ):
                    violations.append(f"{rel}:{node.lineno}: def __getattr__(...)")

        self.assertFalse(
            violations,
            "Found object-level dynamic attribute delegation outside package lazy exports:\n"
            + "\n".join(violations),
        )

    def test_serving_preparer_warmup_uses_infrastructure_ports(self) -> None:
        path = RAG_MODULES_DIR / "app" / "composition" / "serving_runtime_preparer.py"
        rel = path.relative_to(ROOT)
        source = path.read_text(encoding="utf-8-sig")
        tree = ast.parse(source, filename=str(path))
        lines = source.splitlines()
        prohibited = {
            "runtime.data_module.load_graph_data",
            "runtime.index_module.has_collection",
            "runtime.index_module.load_collection",
        }
        violations: list[str] = []

        for node in ast.walk(tree):
            if not isinstance(node, ast.Attribute):
                continue
            chain = ".".join(self._attribute_chain(node))
            if chain in prohibited:
                violations.append(f"{rel}:{node.lineno}: {lines[node.lineno - 1].strip()}")

        self.assertFalse(
            violations,
            "Found serving warmup access that should go through infrastructure ports:\n"
            + "\n".join(violations),
        )

    def test_runtime_manager_collects_diagnostics_through_service(self) -> None:
        path = RAG_MODULES_DIR / "app" / "composition" / "runtime_manager.py"
        rel = path.relative_to(ROOT)
        source = path.read_text(encoding="utf-8-sig")
        tree = ast.parse(source, filename=str(path))
        lines = source.splitlines()
        prohibited = {
            "data_module.get_statistics",
            "index_module.get_collection_stats",
            "routing_workflow.get_route_statistics",
            "retrieval_runtime_profile.to_dict",
        }
        violations: list[str] = []

        for node in ast.walk(tree):
            if not isinstance(node, ast.Attribute):
                continue
            chain = ".".join(self._attribute_chain(node))
            if chain in prohibited:
                violations.append(f"{rel}:{node.lineno}: {lines[node.lineno - 1].strip()}")

        self.assertFalse(
            violations,
            "Found runtime-manager diagnostics access that should go through RuntimeDiagnosticsService:\n"
            + "\n".join(violations),
        )

    def test_runtime_manager_initialization_uses_lifecycle_collaborators(self) -> None:
        path = RAG_MODULES_DIR / "app" / "composition" / "runtime_manager.py"
        rel = path.relative_to(ROOT)
        source = path.read_text(encoding="utf-8-sig")
        tree = ast.parse(source, filename=str(path))
        lines = source.splitlines()
        prohibited = {
            "self.build_bootstrapper.build",
            "self.serving_bootstrapper.build",
            "self.serving_bootstrapper.prepare_with_shared_runtime",
        }
        violations: list[str] = []

        for node in ast.walk(tree):
            if not isinstance(node, ast.Attribute):
                continue
            chain = ".".join(self._attribute_chain(node))
            if chain in prohibited:
                violations.append(f"{rel}:{node.lineno}: {lines[node.lineno - 1].strip()}")

        self.assertFalse(
            violations,
            "Found runtime-manager initialization logic that should be delegated to lifecycle collaborators:\n"
            + "\n".join(violations),
        )

    def test_runtime_manager_constructor_does_not_resolve_lifecycle_collaborators_inline(
        self,
    ) -> None:
        path = RAG_MODULES_DIR / "app" / "composition" / "runtime_manager.py"
        rel = path.relative_to(ROOT)
        source = path.read_text(encoding="utf-8-sig")
        tree = ast.parse(source, filename=str(path))
        violations: list[str] = []

        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "__init__":
                param_names = [arg.arg for arg in node.args.args + node.args.kwonlyargs]
                prohibited_params = {
                    "build_bootstrapper",
                    "serving_bootstrapper",
                    "initialization_service",
                    "readiness_service",
                    "refresh_service",
                    "build_lifecycle_service",
                    "lifecycle_service_composer",
                }
                for param in prohibited_params.intersection(param_names):
                    violations.append(f"{rel}:{node.lineno}: unexpected ctor param '{param}'")
        for rule in APP_COMPOSITION_CALL_BOUNDARIES:
            if rule.path == path:
                violations.extend(self._collect_call_boundary_violations(rule))

        self.assertFalse(
            violations,
            "Found runtime-manager constructor logic that resolves lifecycle collaborators inline:\n"
            + "\n".join(violations),
        )

    def test_public_bootstrapper_facades_do_not_resolve_split_bootstrappers_inline(self) -> None:
        violations: list[str] = []

        for rule in APP_COMPOSITION_DYNAMIC_LOOKUP_BOUNDARIES:
            if rule.path.name == "bootstrap.py":
                violations.extend(self._collect_dynamic_lookup_boundary_violations(rule))

        self.assertFalse(
            violations,
            "Found public bootstrapper facade logic that inspects split bootstrappers inline:\n"
            + "\n".join(violations),
        )

    def test_public_bootstrapper_facades_do_not_bind_components_inline(self) -> None:
        path = RAG_MODULES_DIR / "app" / "bootstrap.py"
        rel = path.relative_to(ROOT)
        source = path.read_text(encoding="utf-8-sig")
        tree = ast.parse(source, filename=str(path))
        lines = source.splitlines()
        violations: list[str] = []

        for node in ast.walk(tree):
            if not isinstance(node, ast.Assign):
                continue
            value_chain = ".".join(self._attribute_chain(node.value))
            for target in node.targets:
                if not isinstance(target, ast.Attribute):
                    continue
                target_chain = ".".join(self._attribute_chain(target))
                if target_chain.startswith("self.") and value_chain.startswith("components."):
                    violations.append(f"{rel}:{node.lineno}: {lines[node.lineno - 1].strip()}")

        self.assertFalse(
            violations,
            "Found public bootstrapper component binding that belongs behind a helper boundary:\n"
            + "\n".join(violations),
        )

    def test_public_bootstrappers_do_not_call_runtime_collaborators_directly(self) -> None:
        path = RAG_MODULES_DIR / "app" / "bootstrap.py"
        rel = path.relative_to(ROOT)
        source = path.read_text(encoding="utf-8-sig")
        tree = ast.parse(source, filename=str(path))
        lines = source.splitlines()
        violations: list[str] = []
        prohibited = {
            "self.factory.build",
            "self.executor.build_knowledge_base",
            "self.executor.rebuild_knowledge_base",
            "self.lifecycle_service.build_ready",
            "self.lifecycle_service.prepare",
            "self.lifecycle_service.prepare_with_shared_runtime",
            "self.bootstrap_service.build",
        }

        for node in ast.walk(tree):
            if not isinstance(node, ast.Attribute):
                continue
            chain = ".".join(self._attribute_chain(node))
            if chain in prohibited:
                violations.append(f"{rel}:{node.lineno}: {lines[node.lineno - 1].strip()}")
        self.assertFalse(
            violations,
            "Found public bootstrapper direct calls into runtime collaborators:\n"
            + "\n".join(violations),
        )

    def test_public_bootstrapper_facades_do_not_construct_runtime_components(self) -> None:
        violations: list[str] = []

        for rule in APP_COMPOSITION_CALL_BOUNDARIES:
            if rule.path.name == "bootstrap.py":
                violations.extend(self._collect_call_boundary_violations(rule))

        self.assertFalse(
            violations,
            "Found public bootstrapper runtime-component construction:\n" + "\n".join(violations),
        )

    def test_system_facade_and_composition_do_not_resolve_bootstrapper_surfaces_inline(
        self,
    ) -> None:
        violations: list[str] = []

        for rule in APP_COMPOSITION_DYNAMIC_LOOKUP_BOUNDARIES:
            if rule.path.name in {"system.py", "system_composer.py"}:
                violations.extend(self._collect_dynamic_lookup_boundary_violations(rule))

        self.assertFalse(
            violations,
            "Found inline bootstrapper-surface resolution outside explicit provider contracts:\n"
            + "\n".join(violations),
        )

    def test_app_composition_roots_do_not_import_retired_provider_components(self) -> None:
        violations: list[str] = []

        for rule in APP_COMPOSITION_IMPORT_BOUNDARIES:
            if rule.path.name == "bootstrapper_composer.py":
                violations.extend(self._collect_import_boundary_violations(rule))

        self.assertFalse(
            violations,
            "Found retired provider_components imports in app composition roots:\n"
            + "\n".join(violations),
        )

    def test_runtime_manager_is_not_wired_with_public_bootstrapper_surfaces(self) -> None:
        path = RAG_MODULES_DIR / "app" / "composition" / "system_composer.py"
        rel = path.relative_to(ROOT)
        source = path.read_text(encoding="utf-8-sig")
        tree = ast.parse(source, filename=str(path))
        violations: list[str] = []
        prohibited_keywords = {
            "build_bootstrapper",
            "lifecycle_service_composer",
            "serving_bootstrapper",
        }

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or self._call_name(node) != "SystemRuntimeManager":
                continue
            keyword_names = {kw.arg for kw in node.keywords if kw.arg is not None}
            for keyword in prohibited_keywords.intersection(keyword_names):
                violations.append(f"{rel}:{node.lineno}: unexpected manager kw '{keyword}'")

        self.assertFalse(
            violations,
            "Found runtime-manager wiring that depends on public bootstrapper surfaces:\n"
            + "\n".join(violations),
        )

    def test_system_facade_collaborators_respect_runtime_access_boundaries(self) -> None:
        violations: list[str] = []

        for rule in APP_COMPOSITION_IMPORT_BOUNDARIES:
            if rule.path.name == "system.py":
                violations.extend(self._collect_import_boundary_violations(rule))
        for rule in APP_COMPOSITION_CALL_BOUNDARIES:
            if rule.path.name == "system.py":
                violations.extend(self._collect_call_boundary_violations(rule))
        for rule in APP_COMPOSITION_ATTRIBUTE_BOUNDARIES:
            if rule.path.name in {
                "system.py",
                "system_answering_service.py",
                "system_facade_support.py",
            }:
                violations.extend(self._collect_attribute_boundary_violations(rule))

        self.assertFalse(
            violations,
            "Found system facade runtime access that bypasses public collaborator boundaries:\n"
            + "\n".join(violations),
        )

    def test_cli_interface_modules_are_retired(self) -> None:
        retired_paths = (
            ROOT / "main_qa.py",
            ROOT / "main_build_kb.py",
            RAG_MODULES_DIR / "interfaces" / "cli_console.py",
            RAG_MODULES_DIR / "app" / "composition" / "system_interactive_service.py",
        )

        self.assertFalse(
            [str(path.relative_to(ROOT)) for path in retired_paths if path.exists()],
            "CLI-only modules should be removed after API-only retirement.",
        )

    def test_system_components_boundary_does_not_expose_runtime_manager_or_cli_services(
        self,
    ) -> None:
        path = RAG_MODULES_DIR / "app" / "composition" / "system_composer.py"
        rel = path.relative_to(ROOT)
        source = path.read_text(encoding="utf-8-sig")
        tree = ast.parse(source, filename=str(path))
        lines = source.splitlines()
        violations: list[str] = []
        prohibited_component_keywords = {"interactive_service", "runtime_manager"}
        prohibited_calls = {"SystemInteractiveService"}

        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                if not isinstance(node.func, ast.Name):
                    continue
                if node.func.id in prohibited_calls:
                    violations.append(f"{rel}:{node.lineno}: {lines[node.lineno - 1].strip()}")
                elif node.func.id == "AdvancedGraphRAGSystemComponents":
                    keyword_names = {kw.arg for kw in node.keywords if kw.arg is not None}
                    for keyword in prohibited_component_keywords.intersection(keyword_names):
                        violations.append(
                            f"{rel}:{node.lineno}: components should not expose {keyword}="
                        )

        self.assertFalse(
            violations,
            "Found system components exposing runtime internals or retired CLI services:\n"
            + "\n".join(violations),
        )

    def test_runtime_manager_does_not_construct_runtime_view_inline(self) -> None:
        path = RAG_MODULES_DIR / "app" / "composition" / "runtime_manager.py"
        rel = path.relative_to(ROOT)
        source = path.read_text(encoding="utf-8-sig")
        tree = ast.parse(source, filename=str(path))
        lines = source.splitlines()
        violations: list[str] = []

        prohibited = {
            "SystemRuntime",
        }

        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func_name = (
                    node.func.id
                    if isinstance(node.func, ast.Name)
                    else node.func.attr
                    if isinstance(node.func, ast.Attribute)
                    else None
                )
                if func_name in prohibited:
                    violations.append(f"{rel}:{node.lineno}: {lines[node.lineno - 1].strip()}")

        self.assertFalse(
            violations,
            "Found runtime-manager runtime view construction that should stay behind state access:\n"
            + "\n".join(violations),
        )

    def test_public_bootstrappers_delegate_to_lifecycle_services(self) -> None:
        path = RAG_MODULES_DIR / "app" / "bootstrap.py"
        rel = path.relative_to(ROOT)
        source = path.read_text(encoding="utf-8-sig")
        tree = ast.parse(source, filename=str(path))
        lines = source.splitlines()
        prohibited = {
            "self.factory.build_knowledge_base",
            "self.factory.rebuild_knowledge_base",
            "self.factory.prepare",
            "self.factory.prepare_with_shared_runtime",
            "self.build_bootstrapper.build",
            "self.serving_bootstrapper.build",
        }
        violations: list[str] = []

        for node in ast.walk(tree):
            if not isinstance(node, ast.Attribute):
                continue
            chain = ".".join(self._attribute_chain(node))
            if chain in prohibited:
                violations.append(f"{rel}:{node.lineno}: {lines[node.lineno - 1].strip()}")

        self.assertFalse(
            violations,
            "Found public bootstrapper orchestration that should be delegated to lifecycle/bootstrap services:\n"
            + "\n".join(violations),
        )

    def test_runtime_manager_build_flow_uses_build_lifecycle_service(self) -> None:
        path = RAG_MODULES_DIR / "app" / "composition" / "runtime_manager.py"
        rel = path.relative_to(ROOT)
        source = path.read_text(encoding="utf-8-sig")
        tree = ast.parse(source, filename=str(path))
        lines = source.splitlines()
        prohibited = {
            "self.build_bootstrapper.build_knowledge_base",
            "self.build_bootstrapper.rebuild_knowledge_base",
            "self.serving_lifecycle_service.refresh_from_build",
        }
        violations: list[str] = []

        for node in ast.walk(tree):
            if not isinstance(node, ast.Attribute):
                continue
            chain = ".".join(self._attribute_chain(node))
            if chain in prohibited:
                violations.append(f"{rel}:{node.lineno}: {lines[node.lineno - 1].strip()}")

        self.assertFalse(
            violations,
            "Found runtime-manager build flow logic that should be delegated to BuildRuntimeLifecycleService:\n"
            + "\n".join(violations),
        )

    def test_runtime_manager_readiness_uses_readiness_service(self) -> None:
        path = RAG_MODULES_DIR / "app" / "composition" / "runtime_manager.py"
        rel = path.relative_to(ROOT)
        source = path.read_text(encoding="utf-8-sig")
        tree = ast.parse(source, filename=str(path))
        lines = source.splitlines()
        prohibited = {
            "self.build_runtime.is_initialized",
            "self.serving_runtime.is_initialized",
        }
        violations: list[str] = []

        for node in ast.walk(tree):
            if not isinstance(node, ast.Attribute):
                continue
            chain = ".".join(self._attribute_chain(node))
            if chain in prohibited:
                violations.append(f"{rel}:{node.lineno}: {lines[node.lineno - 1].strip()}")

        self.assertFalse(
            violations,
            "Found runtime-manager readiness checks that should be delegated to RuntimeReadinessService:\n"
            + "\n".join(violations),
        )

    def test_runtime_services_do_not_depend_on_public_bootstrapper_methods(self) -> None:
        prohibited_accesses = {
            RAG_MODULES_DIR / "app" / "composition" / "runtime_initialization_service.py": {
                "self.build_bootstrapper.build",
                "self.serving_bootstrapper.build",
            },
            RAG_MODULES_DIR / "app" / "composition" / "build_runtime_lifecycle_service.py": {
                "self.build_bootstrapper.build_knowledge_base",
                "self.build_bootstrapper.rebuild_knowledge_base",
                "self.build_runtime_factory.build_knowledge_base",
                "self.build_runtime_factory.rebuild_knowledge_base",
            },
            RAG_MODULES_DIR / "app" / "composition" / "serving_runtime_lifecycle_service.py": {
                "self.serving_runtime_factory.prepare",
                "self.serving_runtime_factory.prepare_with_shared_runtime",
            },
        }
        violations: list[str] = []

        for path, banned in prohibited_accesses.items():
            rel = path.relative_to(ROOT)
            source = path.read_text(encoding="utf-8-sig")
            tree = ast.parse(source, filename=str(path))
            lines = source.splitlines()

            for node in ast.walk(tree):
                if not isinstance(node, ast.Attribute):
                    continue
                chain = ".".join(self._attribute_chain(node))
                if chain in banned:
                    violations.append(f"{rel}:{node.lineno}: {lines[node.lineno - 1].strip()}")

        self.assertFalse(
            violations,
            "Found composition services that still depend on public bootstrapper methods:\n"
            + "\n".join(violations),
        )

    def test_runtime_factories_remain_assembly_only(self) -> None:
        prohibited_accesses = {
            RAG_MODULES_DIR / "app" / "composition" / "build_runtime_factory.py": {
                "self.executor.build_knowledge_base",
                "self.executor.rebuild_knowledge_base",
            },
            RAG_MODULES_DIR / "app" / "composition" / "serving_runtime_factory.py": {
                "self.preparer.prepare",
                "self.preparer.prepare_with_shared_runtime",
                "self.lifecycle_service.build_ready",
            },
        }
        violations: list[str] = []

        for path, banned in prohibited_accesses.items():
            rel = path.relative_to(ROOT)
            source = path.read_text(encoding="utf-8-sig")
            tree = ast.parse(source, filename=str(path))
            lines = source.splitlines()

            for node in ast.walk(tree):
                if not isinstance(node, ast.Attribute):
                    continue
                chain = ".".join(self._attribute_chain(node))
                if chain in banned:
                    violations.append(f"{rel}:{node.lineno}: {lines[node.lineno - 1].strip()}")

        self.assertFalse(
            violations,
            "Found factory logic that should live in dedicated lifecycle services:\n"
            + "\n".join(violations),
        )

    def test_runtime_diagnostics_service_uses_runtime_stats_port(self) -> None:
        path = RAG_MODULES_DIR / "app" / "services" / "runtime_diagnostics_service.py"
        rel = path.relative_to(ROOT)
        source = path.read_text(encoding="utf-8-sig")
        tree = ast.parse(source, filename=str(path))
        lines = source.splitlines()
        prohibited = {
            "infrastructure.data_module.get_statistics",
            "infrastructure.index_module.get_collection_stats",
            "retrieval.routing_workflow.get_route_statistics",
            "retrieval.retrieval_runtime_profile.to_dict",
        }
        violations: list[str] = []

        for node in ast.walk(tree):
            if not isinstance(node, ast.Attribute):
                continue
            chain = ".".join(self._attribute_chain(node))
            if chain in prohibited:
                violations.append(f"{rel}:{node.lineno}: {lines[node.lineno - 1].strip()}")

        self.assertFalse(
            violations,
            "Found diagnostics access that should go through RuntimeStatsAccessPort:\n"
            + "\n".join(violations),
        )

    def test_runtime_manager_shutdown_uses_lifecycle_service(self) -> None:
        path = RAG_MODULES_DIR / "app" / "composition" / "runtime_manager.py"
        rel = path.relative_to(ROOT)
        source = path.read_text(encoding="utf-8-sig")
        tree = ast.parse(source, filename=str(path))
        lines = source.splitlines()
        prohibited = {
            "self.serving_runtime.query_tracer.close",
            "self.serving_runtime.traditional_retrieval.close",
            "self.serving_runtime.graph_rag_retrieval.close",
            "self.build_runtime.knowledge_base_service.close",
            "self.serving_runtime.neo4j_manager.close",
            "self.serving_runtime.retrieval_engines_initialized",
        }
        violations: list[str] = []

        for node in ast.walk(tree):
            if not isinstance(node, ast.Attribute):
                continue
            chain = ".".join(self._attribute_chain(node))
            if chain in prohibited:
                violations.append(f"{rel}:{node.lineno}: {lines[node.lineno - 1].strip()}")

        self.assertFalse(
            violations,
            "Found runtime-manager shutdown access that should go through RuntimeShutdownService:\n"
            + "\n".join(violations),
        )

    def test_build_workflow_artifact_loading_uses_runtime_ports(self) -> None:
        path = RAG_MODULES_DIR / "build_pipeline" / "knowledge_base_workflow.py"
        rel = path.relative_to(ROOT)
        source = path.read_text(encoding="utf-8-sig")
        tree = ast.parse(source, filename=str(path))
        lines = source.splitlines()
        prohibited = {
            "self.data_module.load_graph_data",
            "self.data_module.get_statistics",
            "self.index_module.has_collection",
            "self.index_module.load_collection",
            "self.index_module.build_vector_index",
            "self.index_module.delete_collection",
            "self.index_module.get_collection_stats",
            "self.query_router.get_route_statistics",
        }
        violations: list[str] = []

        for node in ast.walk(tree):
            if not isinstance(node, ast.Attribute):
                continue
            chain = ".".join(self._attribute_chain(node))
            if chain in prohibited:
                violations.append(f"{rel}:{node.lineno}: {lines[node.lineno - 1].strip()}")

        self.assertFalse(
            violations,
            "Found build artifact access that should go through lifecycle ports:\n"
            + "\n".join(violations),
        )

    def test_build_workflow_uses_stats_presenter_and_manifest_lifecycle(self) -> None:
        path = RAG_MODULES_DIR / "build_pipeline" / "knowledge_base_workflow.py"
        rel = path.relative_to(ROOT)
        source = path.read_text(encoding="utf-8-sig")
        tree = ast.parse(source, filename=str(path))
        lines = source.splitlines()
        prohibited = {
            "self.manifest_store.load",
            "self.manifest_store.save",
            "self.runtime_stats_access.get_graph_data_stats",
            "self.runtime_stats_access.get_vector_collection_stats",
            "self.runtime_stats_access.get_route_stats",
        }
        violations: list[str] = []

        for node in ast.walk(tree):
            if not isinstance(node, ast.Attribute):
                continue
            chain = ".".join(self._attribute_chain(node))
            if chain in prohibited:
                violations.append(f"{rel}:{node.lineno}: {lines[node.lineno - 1].strip()}")

        self.assertFalse(
            violations,
            "Found build workflow responsibilities that should live in presenter/lifecycle collaborators:\n"
            + "\n".join(violations),
        )

    def test_build_workflow_uses_build_pipeline_ports_not_concrete_helpers(self) -> None:
        path = RAG_MODULES_DIR / "build_pipeline" / "knowledge_base_workflow.py"
        rel = path.relative_to(ROOT)
        source = path.read_text(encoding="utf-8-sig")
        tree = ast.parse(source, filename=str(path))
        lines = source.splitlines()
        prohibited_calls = {"build_or_load_documents", "SemanticGraphSchemaWriter"}
        prohibited_modules = {
            "rag_modules.build_pipeline.document_artifacts.service",
            "rag_modules.infra.semantic_graph_writer",
        }
        violations: list[str] = []

        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                if node.func.id in prohibited_calls:
                    violations.append(f"{rel}:{node.lineno}: {lines[node.lineno - 1].strip()}")
            elif isinstance(node, ast.ImportFrom):
                module_name = self._resolve_import_from(path, node)
                if module_name in prohibited_modules:
                    violations.append(f"{rel}:{node.lineno}: {lines[node.lineno - 1].strip()}")
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name in prohibited_modules:
                        violations.append(f"{rel}:{node.lineno}: {lines[node.lineno - 1].strip()}")

        self.assertFalse(
            violations,
            "Found build workflow dependencies that should be behind build-pipeline ports:\n"
            + "\n".join(violations),
        )


if __name__ == "__main__":
    unittest.main()

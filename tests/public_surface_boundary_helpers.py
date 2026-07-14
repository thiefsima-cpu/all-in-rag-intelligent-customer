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
        "rag_modules.graph.cache",
        "rag_modules.graph.evidence",
        "rag_modules.graph.query",
        "rag_modules.graph.reasoning",
        "rag_modules.graph.retrieval",
        "rag_modules.graph_data_preparation",
        "rag_modules.graph_indexing",
        "rag_modules.intelligent_query_router",
        "rag_modules.interfaces.api.routes",
        "rag_modules.neo4j_pool",
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
    "rag_modules.build_pipeline.graph_data_preparation": RAG_MODULES_DIR
    / "build_pipeline"
    / "graph_data_preparation.py",
    "rag_modules.evidence_processing.core": RAG_MODULES_DIR / "evidence_processing" / "core.py",
    "rag_modules.interfaces.api.build_job_store": RAG_MODULES_DIR
    / "interfaces"
    / "api"
    / "build_job_store.py",
    "rag_modules.interfaces.api.build_jobs": RAG_MODULES_DIR / "interfaces" / "api" / "build_jobs",
    "rag_modules.query_understanding.planner_service": RAG_MODULES_DIR
    / "query_understanding"
    / "planner_service.py",
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
MISLEADING_COMPAT_DOCSTRING_PATTERNS = (
    re.compile(r"\bcompatibility\s+facade\b", re.IGNORECASE),
    re.compile(r"\bcompatibility\s+re-exports?\b", re.IGNORECASE),
    re.compile(r"\bcompatibility\s+exports?\b", re.IGNORECASE),
    re.compile(r"\bexport\s+shim\b", re.IGNORECASE),
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


class PublicSurfaceBoundaryTestCase(unittest.TestCase):
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
        match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)(?:rc\d+)?(?:\.dev\d+)?", version)
        if match is None:
            raise ValueError(f"Unsupported package version: {version!r}")
        major, minor, patch = (int(part) for part in match.groups())
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


__all__ = (
    "annotations",
    "ast",
    "importlib",
    "re",
    "sys",
    "tomllib",
    "unittest",
    "dataclass",
    "resolve_name",
    "Path",
    "API_PREFIX",
    "API_VERSION",
    "EXTERNAL_PUBLIC_SURFACE",
    "LEGACY_PUBLIC_SURFACE",
    "LEGACY_PUBLIC_SURFACE_REMOVAL_VERSION",
    "LEGACY_PUBLIC_SURFACE_SCAN_RULES",
    "ROOT_PUBLIC_SURFACE",
    "repo_root_facade_module_names",
    "root_facade_module_names",
    "ROOT",
    "RAG_MODULES_DIR",
    "ALLOWED_ROOT_WRAPPERS",
    "PROHIBITED_ROOT_MODULES",
    "PROHIBITED_REPO_ROOT_MODULES",
    "LEGACY_FACADE_MODULES",
    "MIGRATED_ROOT_SHARED_MODULE_FILES",
    "RETIRED_LEGACY_FACADE_MODULES",
    "PROHIBITED_LEGACY_FACADE_MODULES",
    "RETIRED_LATE_MIGRATION_COMPAT_EXPORTS",
    "RETIRED_INTERNAL_COMPAT_SHELLS",
    "RETIRED_INTERNAL_COMPAT_NAMES",
    "RETIRED_PROVIDER_COMPONENTS_PACKAGE",
    "RETIRED_PROVIDER_COMPONENTS_PATH",
    "RETIRED_PROVIDER_COMPONENTS_MODULES",
    "MISLEADING_COMPAT_DOCSTRING_PATTERNS",
    "AttributeBoundaryRule",
    "CallBoundaryRule",
    "DefinitionBoundaryRule",
    "DynamicLookupBoundaryRule",
    "ImportBoundaryRule",
    "APP_COMPOSITION_IMPORT_BOUNDARIES",
    "APP_COMPOSITION_CALL_BOUNDARIES",
    "APP_COMPOSITION_DEFINITION_BOUNDARIES",
    "APP_COMPOSITION_DYNAMIC_LOOKUP_BOUNDARIES",
    "APP_COMPOSITION_ATTRIBUTE_BOUNDARIES",
    "PublicSurfaceBoundaryTestCase",
)

from __future__ import annotations

import ast
import importlib
import unittest
from importlib.util import resolve_name
from pathlib import Path

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
RETIRED_LEGACY_FACADE_MODULES = frozenset(
    {
        "config",
        "rag_modules.graph_data_preparation",
        "rag_modules.graph_indexing",
        "rag_modules.intelligent_query_router",
    }
)
PROHIBITED_LEGACY_FACADE_MODULES = LEGACY_FACADE_MODULES | RETIRED_LEGACY_FACADE_MODULES


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

    @classmethod
    def _resolve_import_from(cls, path: Path, node: ast.ImportFrom) -> str:
        module = node.module or ""
        if node.level == 0:
            return module
        relative_name = "." * node.level + module
        return resolve_name(relative_name, cls._package_name_for_path(path))

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

    def test_retirement_plan_document_states_current_policy(self) -> None:
        plan_path = ROOT / "docs" / "public_surface_retirement_plan.md"
        self.assertTrue(plan_path.exists())
        content = plan_path.read_text(encoding="utf-8")

        for heading in (
            "## Current Policy",
            "## Canonical Packages",
            "## Legacy Bridge Status",
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
            "rag_modules.routing.intelligent_query_router",
            "retired in favor of",
            "rag_modules.compat.*",
            "must not recreate",
            "will fail instead of forwarding",
        ):
            self.assertIn(expected, content)

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
            RAG_MODULES_DIR / "graph_data_preparation.py",
            RAG_MODULES_DIR / "graph_indexing.py",
            RAG_MODULES_DIR / "intelligent_query_router.py",
        }

        self.assertEqual(
            set(),
            {path.relative_to(ROOT) for path in retired_paths if path.exists()},
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
            RAG_MODULES_DIR / "interfaces" / "api" / "service.py": {
                "rag_modules.interfaces.api.services",
            },
            RAG_MODULES_DIR / "generation" / "executor.py": {
                "rag_modules.generation.execution",
            },
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

    def test_composer_modules_are_grouped_by_composition_root(self) -> None:
        composition_dir = RAG_MODULES_DIR / "app" / "composition"
        composer_modules = {path.name for path in composition_dir.glob("*composer.py")}
        self.assertEqual(
            {
                "bootstrapper_composer.py",
                "runtime_lifecycle_service_composer.py",
                "system_composer.py",
            },
            composer_modules,
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
        allowed_definition = (
            RAG_MODULES_DIR / "routing" / "intelligent_query_router.py",
            "def route_query",
        )

        for base_dir in (RAG_MODULES_DIR, ROOT / "scripts"):
            for path in base_dir.rglob("*.py"):
                rel = path.relative_to(ROOT)
                source = path.read_text(encoding="utf-8-sig")
                tree = ast.parse(source, filename=str(path))
                lines = source.splitlines()

                for node in ast.walk(tree):
                    if isinstance(node, ast.FunctionDef) and node.name == "route_query":
                        if not (
                            path == allowed_definition[0]
                            and lines[node.lineno - 1].strip().startswith(allowed_definition[1])
                        ):
                            violations.append(
                                f"{rel}:{node.lineno}: {lines[node.lineno - 1].strip()}"
                            )
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
            RAG_MODULES_DIR / "__init__.py",
            RAG_MODULES_DIR / "generation_integration.py",
            RAG_MODULES_DIR / "compat" / "generation_integration.py",
            RAG_MODULES_DIR / "generation" / "__init__.py",
            RAG_MODULES_DIR / "generation" / "integration.py",
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
        allowed_files = {
            RAG_MODULES_DIR / "generation" / "integration.py",
        }
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
        allowed_files = {
            RAG_MODULES_DIR / "app" / "services" / "__init__.py",
            RAG_MODULES_DIR / "app" / "services" / "question_answer_service.py",
            RAG_MODULES_DIR / "app" / "runtime_service_resolver.py",
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

    def test_runtime_view_delegates_grouped_views_to_builder(self) -> None:
        path = RAG_MODULES_DIR / "app" / "runtime_view.py"
        rel = path.relative_to(ROOT)
        source = path.read_text(encoding="utf-8-sig")
        tree = ast.parse(source, filename=str(path))
        lines = source.splitlines()
        violations: list[str] = []
        found_builder_import = False
        found_builder_calls: set[str] = set()
        prohibited_helpers = {
            "_resolve_query_tracer",
            "_resolve_neo4j_manager",
            "_resolve_data_module",
            "_resolve_index_module",
        }
        prohibited_constructors = {
            "SystemInfrastructureView",
            "SystemRetrievalView",
            "SystemServicesView",
            "QuestionAnswerService",
            "QuestionAnswerServiceResolver",
        }

        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                module_name = self._resolve_import_from(path, node)
                if module_name.endswith("runtime_view_builder") and any(
                    alias.name == "SystemRuntimeViewBuilder" for alias in node.names
                ):
                    found_builder_import = True
                elif module_name in {
                    "rag_modules.app.services.question_answer_service",
                    "rag_modules.app.runtime_service_resolver",
                }:
                    violations.append(f"{rel}:{node.lineno}: {lines[node.lineno - 1].strip()}")
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "rag_modules.app.runtime_view_builder":
                        found_builder_import = True
                    elif alias.name in {
                        "rag_modules.app.services.question_answer_service",
                        "rag_modules.app.runtime_service_resolver",
                    }:
                        violations.append(f"{rel}:{node.lineno}: {lines[node.lineno - 1].strip()}")
            elif isinstance(node, ast.FunctionDef) and node.name in prohibited_helpers:
                violations.append(f"{rel}:{node.lineno}: {lines[node.lineno - 1].strip()}")
            elif isinstance(node, ast.Call):
                func_name = (
                    node.func.id
                    if isinstance(node.func, ast.Name)
                    else node.func.attr
                    if isinstance(node.func, ast.Attribute)
                    else None
                )
                if func_name in prohibited_constructors:
                    violations.append(f"{rel}:{node.lineno}: {lines[node.lineno - 1].strip()}")
                if isinstance(node.func, ast.Attribute):
                    chain = ".".join(self._attribute_chain(node.func))
                    if chain.startswith("self._view_builder.build_"):
                        found_builder_calls.add(chain)

        self.assertTrue(
            found_builder_import,
            "runtime view should import SystemRuntimeViewBuilder instead of assembling grouped views inline",
        )
        self.assertEqual(
            found_builder_calls,
            {
                "self._view_builder.build_infrastructure_view",
                "self._view_builder.build_retrieval_view",
                "self._view_builder.build_services_view",
            },
            "runtime view should delegate grouped view assembly to SystemRuntimeViewBuilder",
        )
        self.assertFalse(
            violations,
            "Found runtime-view assembly that should live in the builder/resolver layer:\n"
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

    def test_runtime_manager_constructor_uses_precomposed_lifecycle_bundle(self) -> None:
        path = RAG_MODULES_DIR / "app" / "composition" / "runtime_manager.py"
        rel = path.relative_to(ROOT)
        source = path.read_text(encoding="utf-8-sig")
        tree = ast.parse(source, filename=str(path))
        lines = source.splitlines()
        violations: list[str] = []
        found_init = False
        found_lifecycle_services_param = False

        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "__init__":
                found_init = True
                param_names = [arg.arg for arg in node.args.args + node.args.kwonlyargs]
                found_lifecycle_services_param = "lifecycle_services" in param_names
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
            elif isinstance(node, ast.Call):
                func_name = (
                    node.func.id
                    if isinstance(node.func, ast.Name)
                    else node.func.attr
                    if isinstance(node.func, ast.Attribute)
                    else None
                )
                if func_name in {"getattr", "compose"}:
                    violations.append(f"{rel}:{node.lineno}: {lines[node.lineno - 1].strip()}")

        self.assertTrue(found_init, "runtime manager should define __init__")
        self.assertTrue(
            found_lifecycle_services_param,
            "runtime manager should accept a lifecycle_services bundle",
        )
        self.assertFalse(
            violations,
            "Found runtime-manager constructor logic that should be replaced by a precomposed lifecycle bundle:\n"
            + "\n".join(violations),
        )

    def test_graph_bootstrapper_uses_composer_not_inline_adapter_logic(self) -> None:
        path = RAG_MODULES_DIR / "app" / "bootstrap.py"
        rel = path.relative_to(ROOT)
        source = path.read_text(encoding="utf-8-sig")
        tree = ast.parse(source, filename=str(path))
        lines = source.splitlines()
        violations: list[str] = []

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if not isinstance(node.func, ast.Name) or node.func.id != "getattr":
                continue
            if not node.args:
                continue
            owner = ".".join(self._attribute_chain(node.args[0]))
            if owner in {"self.build_bootstrapper", "self.serving_bootstrapper"}:
                violations.append(f"{rel}:{node.lineno}: {lines[node.lineno - 1].strip()}")

        self.assertFalse(
            violations,
            "Found graph-bootstrapper constructor adapter logic that should live in RuntimeLifecycleServiceComposer:\n"
            + "\n".join(violations),
        )

    def test_public_bootstrappers_share_component_binding_base(self) -> None:
        support_path = RAG_MODULES_DIR / "app" / "bootstrap_facade_support.py"
        support_rel = support_path.relative_to(ROOT)
        support_source = support_path.read_text(encoding="utf-8-sig")
        support_tree = ast.parse(support_source, filename=str(support_path))
        support_lines = support_source.splitlines()
        path = RAG_MODULES_DIR / "app" / "bootstrap.py"
        rel = path.relative_to(ROOT)
        source = path.read_text(encoding="utf-8-sig")
        tree = ast.parse(source, filename=str(path))
        lines = source.splitlines()
        found_base_class = False
        found_compose_and_bind = False
        found_build_invocation_adapter = False
        found_serving_invocation_adapter = False
        found_graph_invocation_adapter = False
        found_support_import = False
        violations: list[str] = []

        for node in ast.walk(support_tree):
            if isinstance(node, ast.ClassDef) and node.name == "_ComposedBootstrapperFacade":
                found_base_class = True
            elif (
                isinstance(node, ast.ClassDef) and node.name == "BuildBootstrapperInvocationAdapter"
            ):
                found_build_invocation_adapter = True
            elif (
                isinstance(node, ast.ClassDef)
                and node.name == "ServingBootstrapperInvocationAdapter"
            ):
                found_serving_invocation_adapter = True
            elif (
                isinstance(node, ast.ClassDef) and node.name == "GraphBootstrapperInvocationAdapter"
            ):
                found_graph_invocation_adapter = True
            elif isinstance(node, ast.FunctionDef) and node.name == "_compose_and_bind":
                found_compose_and_bind = True
            elif isinstance(node, ast.Assign):
                value_chain = ".".join(self._attribute_chain(node.value))
                for target in node.targets:
                    if not isinstance(target, ast.Attribute):
                        continue
                    target_chain = ".".join(self._attribute_chain(target))
                    if target_chain.startswith("self.") and value_chain.startswith("components."):
                        violations.append(
                            f"{support_rel}:{node.lineno}: {support_lines[node.lineno - 1].strip()}"
                        )

        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                module_name = self._resolve_import_from(path, node)
                imported_names = {alias.name for alias in node.names}
                if module_name.endswith("bootstrap_facade_support") and {
                    "_ComposedBootstrapperFacade",
                    "BuildBootstrapperInvocationAdapter",
                    "ServingBootstrapperInvocationAdapter",
                    "GraphBootstrapperInvocationAdapter",
                }.issubset(imported_names):
                    found_support_import = True
            elif isinstance(node, ast.ClassDef) and node.name == "_ComposedBootstrapperFacade":
                violations.append(f"{rel}:{node.lineno}: {lines[node.lineno - 1].strip()}")
            elif isinstance(node, ast.Assign):
                value_chain = ".".join(self._attribute_chain(node.value))
                for target in node.targets:
                    if not isinstance(target, ast.Attribute):
                        continue
                    target_chain = ".".join(self._attribute_chain(target))
                    if target_chain.startswith("self.") and value_chain.startswith("components."):
                        violations.append(f"{rel}:{node.lineno}: {lines[node.lineno - 1].strip()}")

        self.assertTrue(
            found_base_class,
            "bootstrap facade support should define a shared _ComposedBootstrapperFacade base",
        )
        self.assertTrue(
            found_compose_and_bind,
            "bootstrap facade support should centralize component binding in _compose_and_bind()",
        )
        self.assertTrue(
            found_build_invocation_adapter,
            "bootstrap facade support should define a BuildBootstrapperInvocationAdapter",
        )
        self.assertTrue(
            found_serving_invocation_adapter,
            "bootstrap facade support should define a ServingBootstrapperInvocationAdapter",
        )
        self.assertTrue(
            found_graph_invocation_adapter,
            "bootstrap facade support should define a GraphBootstrapperInvocationAdapter",
        )
        self.assertTrue(
            found_support_import,
            "bootstrap module should import the shared facade base and invocation strategies from bootstrap_facade_support",
        )
        self.assertFalse(
            violations,
            "Found inline component binding that should use the shared bootstrapper facade base:\n"
            + "\n".join(violations),
        )

    def test_public_bootstrappers_use_invocation_adapter_not_direct_boundary_calls(self) -> None:
        path = RAG_MODULES_DIR / "app" / "bootstrap.py"
        rel = path.relative_to(ROOT)
        source = path.read_text(encoding="utf-8-sig")
        tree = ast.parse(source, filename=str(path))
        lines = source.splitlines()
        found_invocation_calls: set[str] = set()
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
            if chain.startswith("self._invocations."):
                found_invocation_calls.add(chain)

        self.assertEqual(
            found_invocation_calls,
            {
                "self._invocations.build_runtime",
                "self._invocations.build_knowledge_base",
                "self._invocations.rebuild_knowledge_base",
                "self._invocations.build_serving_runtime",
                "self._invocations.prepare_serving_runtime",
                "self._invocations.prepare_serving_runtime_with_shared_runtime",
                "self._invocations.build_system_runtime",
            },
            "bootstrap module should route public operations through BootstrapperInvocationAdapter",
        )
        self.assertFalse(
            violations,
            "Found direct boundary calls that should be routed through BootstrapperInvocationAdapter:\n"
            + "\n".join(violations),
        )

    def test_graph_bootstrapper_uses_bootstrapper_composer_not_inline_service_assembly(
        self,
    ) -> None:
        path = RAG_MODULES_DIR / "app" / "bootstrap.py"
        rel = path.relative_to(ROOT)
        source = path.read_text(encoding="utf-8-sig")
        tree = ast.parse(source, filename=str(path))
        lines = source.splitlines()
        violations: list[str] = []

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if isinstance(node.func, ast.Name) and node.func.id in {
                "BuildBootstrapper",
                "ServingBootstrapper",
                "SystemRuntimeBootstrapService",
            }:
                violations.append(f"{rel}:{node.lineno}: {lines[node.lineno - 1].strip()}")

        self.assertFalse(
            violations,
            "Found graph-bootstrapper assembly that should live in GraphRAGBootstrapperComposer:\n"
            + "\n".join(violations),
        )

    def test_serving_bootstrapper_uses_composer_not_inline_lifecycle_resolution(self) -> None:
        path = RAG_MODULES_DIR / "app" / "bootstrap.py"
        rel = path.relative_to(ROOT)
        source = path.read_text(encoding="utf-8-sig")
        tree = ast.parse(source, filename=str(path))
        lines = source.splitlines()
        violations: list[str] = []

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if not isinstance(node.func, ast.Name) or node.func.id != "getattr":
                continue
            if not node.args:
                continue
            owner = ".".join(self._attribute_chain(node.args[0]))
            if owner == "self.factory":
                violations.append(f"{rel}:{node.lineno}: {lines[node.lineno - 1].strip()}")

        self.assertFalse(
            violations,
            "Found serving-bootstrapper lifecycle resolution that should live in ServingBootstrapperComposer:\n"
            + "\n".join(violations),
        )

    def test_build_bootstrapper_uses_composer_not_inline_component_resolution(self) -> None:
        path = RAG_MODULES_DIR / "app" / "bootstrap.py"
        rel = path.relative_to(ROOT)
        source = path.read_text(encoding="utf-8-sig")
        tree = ast.parse(source, filename=str(path))
        lines = source.splitlines()
        violations: list[str] = []

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if isinstance(node.func, ast.Name) and node.func.id in {
                "BuildRuntimeFactory",
                "BuildRuntimeExecutor",
            }:
                violations.append(f"{rel}:{node.lineno}: {lines[node.lineno - 1].strip()}")

        self.assertFalse(
            violations,
            "Found build-bootstrapper assembly that should live in BuildBootstrapperComposer:\n"
            + "\n".join(violations),
        )

    def test_system_constructor_uses_system_composer_not_inline_provider_resolution(self) -> None:
        path = RAG_MODULES_DIR / "app" / "system.py"
        rel = path.relative_to(ROOT)
        source = path.read_text(encoding="utf-8-sig")
        tree = ast.parse(source, filename=str(path))
        lines = source.splitlines()
        violations: list[str] = []

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if not isinstance(node.func, ast.Name) or node.func.id != "getattr":
                continue
            if not node.args:
                continue
            owner = node.args[0]
            if isinstance(owner, ast.Name) and owner.id in {
                "bootstrapper",
                "build_bootstrapper",
                "serving_bootstrapper",
            }:
                violations.append(f"{rel}:{node.lineno}: {lines[node.lineno - 1].strip()}")

        self.assertFalse(
            violations,
            "Found system constructor provider/bootstrapper resolution that should live in AdvancedGraphRAGSystemComposer:\n"
            + "\n".join(violations),
        )

    def test_system_composer_uses_provider_surface_resolver_not_inline_provider_resolution(
        self,
    ) -> None:
        path = RAG_MODULES_DIR / "app" / "composition" / "system_composer.py"
        rel = path.relative_to(ROOT)
        source = path.read_text(encoding="utf-8-sig")
        tree = ast.parse(source, filename=str(path))
        lines = source.splitlines()
        violations: list[str] = []

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if not isinstance(node.func, ast.Name) or node.func.id != "getattr":
                continue
            if not node.args:
                continue
            owner = node.args[0]
            if isinstance(owner, ast.Name) and owner.id in {
                "bootstrapper",
                "build_bootstrapper",
                "serving_bootstrapper",
            }:
                violations.append(f"{rel}:{node.lineno}: {lines[node.lineno - 1].strip()}")

        self.assertFalse(
            violations,
            "Found system-composer provider resolution that should live in RuntimeProviderSurfaceResolver:\n"
            + "\n".join(violations),
        )

    def test_bootstrapper_composers_use_provider_resolver(self) -> None:
        target_paths = {
            RAG_MODULES_DIR / "app" / "composition" / "bootstrapper_composer.py",
        }
        violations: list[str] = []

        for path in target_paths:
            rel = path.relative_to(ROOT)
            source = path.read_text(encoding="utf-8-sig")
            tree = ast.parse(source, filename=str(path))
            lines = source.splitlines()
            found_provider_resolver_import = False

            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    module_name = self._resolve_import_from(path, node)
                    if module_name.endswith("provider_resolution") and any(
                        alias.name == "RuntimeComponentProviderResolver" for alias in node.names
                    ):
                        found_provider_resolver_import = True
                    if module_name.endswith("provider_components.runtime") and any(
                        alias.name == "DefaultRuntimeComponentProvider" for alias in node.names
                    ):
                        violations.append(f"{rel}:{node.lineno}: {lines[node.lineno - 1].strip()}")
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name.endswith("provider_resolution"):
                            found_provider_resolver_import = True
                        if alias.name.endswith("provider_components.runtime"):
                            violations.append(
                                f"{rel}:{node.lineno}: {lines[node.lineno - 1].strip()}"
                            )

            self.assertTrue(
                found_provider_resolver_import,
                f"{rel} should import RuntimeComponentProviderResolver",
            )

        self.assertFalse(
            violations,
            "Found inline default-provider resolution that should live in RuntimeComponentProviderResolver:\n"
            + "\n".join(violations),
        )

    def test_graph_bootstrapper_composer_resolves_surface_and_builds_bootstrap_service(
        self,
    ) -> None:
        path = RAG_MODULES_DIR / "app" / "composition" / "bootstrapper_composer.py"
        rel = path.relative_to(ROOT)
        source = path.read_text(encoding="utf-8-sig")
        tree = ast.parse(source, filename=str(path))
        class_node = next(
            node
            for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name == "GraphRAGBootstrapperComposer"
        )
        found_surface_composer = False
        found_bootstrap_service_composer = False
        violations: list[str] = []

        for node in ast.walk(class_node):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
                continue
            if node.func.id == "GraphBootstrapperSurfaceComposer":
                found_surface_composer = True
            elif node.func.id == "SystemRuntimeBootstrapServiceComposer":
                found_bootstrap_service_composer = True
            elif node.func.id in {
                "BuildBootstrapper",
                "ServingBootstrapper",
            }:
                violations.append(
                    f"{rel}:{node.lineno}: {node.func.id} should be composed by the surface composer"
                )
        self.assertTrue(
            found_surface_composer,
            "graph bootstrapper composer should delegate split bootstrapper assembly to GraphBootstrapperSurfaceComposer",
        )
        self.assertTrue(
            found_bootstrap_service_composer,
            "graph bootstrapper composer should delegate bootstrap-service assembly",
        )
        self.assertFalse(
            violations,
            "Found graph-bootstrapper assembly boundary violations:\n" + "\n".join(violations),
        )

    def test_bootstrap_service_composer_wires_system_runtime_bootstrap_service(self) -> None:
        path = RAG_MODULES_DIR / "app" / "composition" / "bootstrapper_composer.py"
        rel = path.relative_to(ROOT)
        source = path.read_text(encoding="utf-8-sig")
        tree = ast.parse(source, filename=str(path))
        class_node = next(
            node
            for node in tree.body
            if isinstance(node, ast.ClassDef)
            and node.name == "SystemRuntimeBootstrapServiceComposer"
        )
        found_lifecycle_composer = False
        found_bootstrap_service = False
        violations: list[str] = []

        for node in ast.walk(class_node):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
                continue
            if node.func.id == "RuntimeLifecycleServiceComposer":
                found_lifecycle_composer = True
            elif node.func.id == "SystemRuntimeBootstrapService":
                found_bootstrap_service = True
                keyword_names = {kw.arg for kw in node.keywords if kw.arg is not None}
                for required in (
                    "build_runtime_factory",
                    "serving_runtime_lifecycle_service",
                ):
                    if required not in keyword_names:
                        violations.append(f"{rel}:{node.lineno}: missing {required}=")

        self.assertTrue(
            found_lifecycle_composer,
            "bootstrap-service composer should adapt bootstrappers through RuntimeLifecycleServiceComposer",
        )
        self.assertTrue(
            found_bootstrap_service,
            "bootstrap-service composer should construct SystemRuntimeBootstrapService",
        )
        self.assertFalse(
            violations,
            "Found bootstrap-service composer wiring gaps:\n" + "\n".join(violations),
        )

    def test_runtime_infrastructure_composer_wires_runtime_manager_with_lifecycle_bundle(
        self,
    ) -> None:
        path = RAG_MODULES_DIR / "app" / "composition" / "system_composer.py"
        rel = path.relative_to(ROOT)
        source = path.read_text(encoding="utf-8-sig")
        tree = ast.parse(source, filename=str(path))
        class_node = next(
            node
            for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name == "SystemRuntimeInfrastructureComposer"
        )
        found_runtime_manager_call = False
        saw_lifecycle_services_keyword = False
        found_stats_access_call = False
        found_diagnostics_provider_call = False
        found_shutdown_provider_call = False
        found_state_store_return = False
        violations: list[str] = []

        for node in ast.walk(class_node):
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name) and node.func.id == "SystemRuntimeManager":
                    found_runtime_manager_call = True
                    keyword_names = {kw.arg for kw in node.keywords if kw.arg is not None}
                    saw_lifecycle_services_keyword = "lifecycle_services" in keyword_names
                    prohibited_keywords = {
                        "build_bootstrapper",
                        "serving_bootstrapper",
                        "lifecycle_service_composer",
                    }
                    for keyword in prohibited_keywords.intersection(keyword_names):
                        violations.append(f"{rel}:{node.lineno}: unexpected manager kw '{keyword}'")
                    if "runtime_state_store" not in keyword_names:
                        violations.append(f"{rel}:{node.lineno}: missing runtime_state_store=")
                    if not saw_lifecycle_services_keyword:
                        violations.append(f"{rel}:{node.lineno}: missing lifecycle_services=")
                    if (
                        "diagnostics_service" not in keyword_names
                        or "shutdown_service" not in keyword_names
                    ):
                        violations.append(
                            f"{rel}:{node.lineno}: manager should be wired with explicit services"
                        )
                elif isinstance(node.func, ast.Attribute):
                    chain = ".".join(self._attribute_chain(node.func))
                    if chain == "provider_surface.diagnostics.provide_runtime_stats_access":
                        found_stats_access_call = True
                    elif (
                        chain == "provider_surface.diagnostics.provide_runtime_diagnostics_service"
                    ):
                        found_diagnostics_provider_call = True
                    elif chain == "provider_surface.lifecycle.provide_runtime_shutdown_service":
                        found_shutdown_provider_call = True
                elif (
                    isinstance(node.func, ast.Name)
                    and node.func.id == "SystemRuntimeInfrastructure"
                ):
                    keyword_names = {kw.arg for kw in node.keywords if kw.arg is not None}
                    found_state_store_return = "runtime_state_store" in keyword_names
                    if "runtime_manager" not in keyword_names:
                        violations.append(f"{rel}:{node.lineno}: missing runtime_manager=")
                    if "runtime_state_store" not in keyword_names:
                        violations.append(f"{rel}:{node.lineno}: missing runtime_state_store=")

        self.assertTrue(
            found_runtime_manager_call,
            "runtime infrastructure composer should instantiate SystemRuntimeManager",
        )
        self.assertTrue(
            saw_lifecycle_services_keyword,
            "runtime infrastructure composer should pass lifecycle_services into SystemRuntimeManager",
        )
        self.assertTrue(
            found_stats_access_call,
            "runtime infrastructure composer should resolve runtime_stats_access from the provider surface",
        )
        self.assertTrue(
            found_diagnostics_provider_call,
            "runtime infrastructure composer should resolve diagnostics_service from the diagnostics provider",
        )
        self.assertTrue(
            found_shutdown_provider_call,
            "runtime infrastructure composer should resolve shutdown_service from the lifecycle provider",
        )
        self.assertTrue(
            found_state_store_return,
            "runtime infrastructure bundle should carry runtime_state_store",
        )
        self.assertFalse(
            violations,
            "Found runtime-infrastructure manager wiring that bypasses lifecycle bundle assembly:\n"
            + "\n".join(violations),
        )

    def test_system_answering_uses_question_answer_service_contract(self) -> None:
        path = RAG_MODULES_DIR / "app" / "system.py"
        rel = path.relative_to(ROOT)
        source = path.read_text(encoding="utf-8-sig")
        tree = ast.parse(source, filename=str(path))
        lines = source.splitlines()
        violations: list[str] = []
        found_answering_service_call = False

        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                chain = ".".join(self._attribute_chain(node.func))
                if chain in {
                    "self.answering_service.answer_question",
                    "self.answering_service.answer_question_response",
                }:
                    found_answering_service_call = True
                if chain in {
                    "self.facade_support.answer_question",
                    "self.facade_support.answer_question_response",
                }:
                    violations.append(f"{rel}:{node.lineno}: {lines[node.lineno - 1].strip()}")
            elif isinstance(node, ast.Attribute):
                chain = ".".join(self._attribute_chain(node))
                if chain == "services.answer_workflow":
                    violations.append(f"{rel}:{node.lineno}: {lines[node.lineno - 1].strip()}")

        self.assertTrue(
            found_answering_service_call,
            "system answering entrypoints should delegate through answering_service",
        )
        self.assertFalse(
            violations,
            "Found system answering logic that should route through answering_service/question_answer_service contract:\n"
            + "\n".join(violations),
        )

    def test_system_runtime_and_legacy_access_use_facade_support(self) -> None:
        path = RAG_MODULES_DIR / "app" / "system.py"
        rel = path.relative_to(ROOT)
        source = path.read_text(encoding="utf-8-sig")
        tree = ast.parse(source, filename=str(path))
        lines = source.splitlines()
        violations: list[str] = []
        found_operations_service_call = False

        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                module_name = self._resolve_import_from(path, node)
                if module_name == "rag_modules.interfaces.cli_console":
                    violations.append(f"{rel}:{node.lineno}: {lines[node.lineno - 1].strip()}")
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "rag_modules.interfaces.cli_console":
                        violations.append(f"{rel}:{node.lineno}: {lines[node.lineno - 1].strip()}")
            elif isinstance(node, ast.Call):
                func_name = (
                    node.func.id
                    if isinstance(node.func, ast.Name)
                    else node.func.attr
                    if isinstance(node.func, ast.Attribute)
                    else None
                )
                if func_name in {"resolve_grouped_legacy_attribute", "merge_legacy_dir_names"}:
                    violations.append(f"{rel}:{node.lineno}: {lines[node.lineno - 1].strip()}")
                elif isinstance(node.func, ast.Attribute):
                    chain = ".".join(self._attribute_chain(node.func))
                    if chain == "self.runtime_manager.runtime_view":
                        violations.append(f"{rel}:{node.lineno}: {lines[node.lineno - 1].strip()}")
                    if chain.startswith("self.operations_service."):
                        found_operations_service_call = True
                    if chain == "self.interactive_service.run_interactive":
                        violations.append(f"{rel}:{node.lineno}: {lines[node.lineno - 1].strip()}")
                    if chain == "InteractiveCliConsole":
                        violations.append(f"{rel}:{node.lineno}: {lines[node.lineno - 1].strip()}")
            elif isinstance(node, ast.Attribute):
                chain = ".".join(self._attribute_chain(node))
                if chain.startswith("self.interactive_service") or chain in {
                    "self.runtime_manager",
                    "self.runtime_manager.runtime",
                    "self.runtime_manager.initialize_build_runtime",
                    "self.runtime_manager.initialize_serving_runtime",
                    "self.runtime_manager.initialize_system",
                    "self.runtime_manager.is_initialized",
                    "self.runtime_manager.is_build_initialized",
                    "self.runtime_manager.is_serving_initialized",
                    "self.runtime_manager.build_knowledge_base",
                    "self.runtime_manager.rebuild_knowledge_base",
                    "self.runtime_manager.collect_system_stats",
                    "self.runtime_manager.collect_startup_diagnostics",
                    "self.runtime_manager.require_ready",
                    "self.runtime_manager.close",
                }:
                    violations.append(f"{rel}:{node.lineno}: {lines[node.lineno - 1].strip()}")

        self.assertTrue(
            found_operations_service_call,
            "system operational entrypoints should delegate through operations_service",
        )
        self.assertFalse(
            violations,
            "Found system facade access that should be delegated to operations_service/SystemFacadeSupport:\n"
            + "\n".join(violations),
        )

    def test_system_facade_support_uses_runtime_state_store_for_runtime_access(self) -> None:
        path = RAG_MODULES_DIR / "app" / "composition" / "system_facade_support.py"
        rel = path.relative_to(ROOT)
        source = path.read_text(encoding="utf-8-sig")
        tree = ast.parse(source, filename=str(path))
        lines = source.splitlines()
        violations: list[str] = []
        found_store_import = False
        found_store_access = False

        prohibited = {
            "self.runtime_manager.runtime",
            "self.runtime_manager.build_runtime",
            "self.runtime_manager.serving_runtime",
            "self.runtime_manager.runtime_view",
            "self.runtime_manager.artifact_manifest",
            "self.runtime_manager.artifacts_ready",
            "self.runtime_manager.system_ready",
            "self.runtime_manager.compose_runtime",
            "self.runtime_manager.is_serving_initialized",
            "self.runtime_manager.initialize_serving_runtime",
            "self.runtime_manager.require_ready",
        }

        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                module_name = self._resolve_import_from(path, node)
                if module_name.endswith("runtime_state_store") and any(
                    alias.name == "RuntimeStateStore" for alias in node.names
                ):
                    found_store_import = True
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "rag_modules.app.composition.runtime_state_store":
                        found_store_import = True
            elif isinstance(node, ast.Attribute):
                chain = ".".join(self._attribute_chain(node))
                if chain in prohibited:
                    violations.append(f"{rel}:{node.lineno}: {lines[node.lineno - 1].strip()}")
                if chain.startswith("self.runtime_state_store."):
                    found_store_access = True

        self.assertTrue(
            found_store_import,
            "system facade support should depend on RuntimeStateStore for runtime state access",
        )
        self.assertTrue(
            found_store_access,
            "system facade support should use runtime_state_store for runtime/build/serving access",
        )
        self.assertFalse(
            violations,
            "Found facade-support runtime access that should come from RuntimeStateStore:\n"
            + "\n".join(violations),
        )

    def test_system_answering_service_owns_answering_orchestration(self) -> None:
        path = RAG_MODULES_DIR / "app" / "composition" / "system_answering_service.py"
        rel = path.relative_to(ROOT)
        source = path.read_text(encoding="utf-8-sig")
        tree = ast.parse(source, filename=str(path))
        lines = source.splitlines()
        found_backend_access = False
        found_store_access = False
        violations: list[str] = []

        prohibited = {
            "self.facade_support.answer_question",
            "self.facade_support.answer_question_response",
        }

        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute):
                chain = ".".join(self._attribute_chain(node))
                if chain.startswith("self.backend."):
                    found_backend_access = True
                if chain.startswith("self.runtime_manager."):
                    violations.append(f"{rel}:{node.lineno}: {lines[node.lineno - 1].strip()}")
                if chain.startswith("self.runtime_state_store."):
                    found_store_access = True
                if chain in prohibited:
                    violations.append(f"{rel}:{node.lineno}: {lines[node.lineno - 1].strip()}")

        self.assertTrue(
            found_backend_access,
            "system answering service should orchestrate readiness through backend contract",
        )
        self.assertTrue(
            found_store_access,
            "system answering service should resolve runtime-backed services through runtime_state_store",
        )
        self.assertFalse(
            violations,
            "Found answering-service logic that should not route back through facade support:\n"
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

    def test_system_composer_delegates_to_sub_composers(self) -> None:
        path = RAG_MODULES_DIR / "app" / "composition" / "system_composer.py"
        rel = path.relative_to(ROOT)
        source = path.read_text(encoding="utf-8-sig")
        tree = ast.parse(source, filename=str(path))
        class_node = next(
            node
            for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name == "AdvancedGraphRAGSystemComposer"
        )
        found_bootstrapper_surface_composer = False
        found_runtime_infrastructure_composer = False
        found_application_service_composer = False
        found_components_field = False
        violations: list[str] = []
        prohibited_calls = {
            "GraphRAGBootstrapper",
            "SystemRuntimeManager",
            "SystemFacadeSupport",
            "SystemOperationsService",
            "SystemAnsweringService",
            "SystemInteractiveService",
        }

        for node in ast.walk(class_node):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                if node.func.id in prohibited_calls:
                    violations.append(
                        f"{rel}:{node.lineno}: {node.func.id} should be composed in a dedicated sub-composer"
                    )
                elif node.func.id == "SystemBootstrapperSurfaceComposer":
                    found_bootstrapper_surface_composer = True
                elif node.func.id == "SystemRuntimeInfrastructureComposer":
                    found_runtime_infrastructure_composer = True
                elif node.func.id == "SystemApplicationServiceComposer":
                    found_application_service_composer = True
                elif node.func.id == "AdvancedGraphRAGSystemComponents":
                    keyword_names = {kw.arg for kw in node.keywords if kw.arg is not None}
                    found_components_field = "facade_support" in keyword_names
                    if "facade_support" not in keyword_names:
                        violations.append(f"{rel}:{node.lineno}: missing facade_support=")
                    if "runtime_state_store" not in keyword_names:
                        violations.append(
                            f"{rel}:{node.lineno}: missing components runtime_state_store="
                        )
                    if "operations_service" not in keyword_names:
                        violations.append(f"{rel}:{node.lineno}: missing operations_service=")
                    if "answering_service" not in keyword_names:
                        violations.append(f"{rel}:{node.lineno}: missing answering_service=")
                    if "runtime_manager" in keyword_names:
                        violations.append(
                            f"{rel}:{node.lineno}: components should not expose runtime_manager="
                        )

        self.assertTrue(
            found_bootstrapper_surface_composer,
            "system composer should delegate bootstrapper-surface resolution to SystemBootstrapperSurfaceComposer",
        )
        self.assertTrue(
            found_runtime_infrastructure_composer,
            "system composer should delegate runtime assembly to SystemRuntimeInfrastructureComposer",
        )
        self.assertTrue(
            found_application_service_composer,
            "system composer should delegate app-service assembly to SystemApplicationServiceComposer",
        )
        self.assertTrue(
            found_components_field,
            "system components should carry facade_support",
        )
        self.assertFalse(
            violations,
            "Found system-composer logic that should be delegated to sub-composers:\n"
            + "\n".join(violations),
        )

    def test_application_service_composer_wires_facade_support(self) -> None:
        path = RAG_MODULES_DIR / "app" / "composition" / "system_composer.py"
        rel = path.relative_to(ROOT)
        source = path.read_text(encoding="utf-8-sig")
        tree = ast.parse(source, filename=str(path))
        class_node = next(
            node
            for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name == "SystemApplicationServiceComposer"
        )
        found_support_call = False
        found_services_bundle = False
        found_support_state_store = False
        found_operations_call = False
        found_operations_manager = False
        found_answering_call = False
        found_answering_state_store = False
        found_answering_manager = False
        violations: list[str] = []

        for node in ast.walk(class_node):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                if node.func.id == "SystemFacadeSupport":
                    found_support_call = True
                    keyword_names = {kw.arg for kw in node.keywords if kw.arg is not None}
                    found_support_state_store = "runtime_state_store" in keyword_names
                    if "runtime_state_store" not in keyword_names:
                        violations.append(
                            f"{rel}:{node.lineno}: missing facade runtime_state_store="
                        )
                    if "runtime_manager" in keyword_names:
                        violations.append(
                            f"{rel}:{node.lineno}: facade support should not take runtime_manager="
                        )
                elif node.func.id == "SystemOperationsService":
                    found_operations_call = True
                    keyword_names = {kw.arg for kw in node.keywords if kw.arg is not None}
                    found_operations_manager = "backend" in keyword_names
                    if "backend" not in keyword_names:
                        violations.append(f"{rel}:{node.lineno}: missing operations backend=")
                elif node.func.id == "SystemAnsweringService":
                    found_answering_call = True
                    keyword_names = {kw.arg for kw in node.keywords if kw.arg is not None}
                    found_answering_state_store = "runtime_state_store" in keyword_names
                    found_answering_manager = "backend" in keyword_names
                    if "runtime_state_store" not in keyword_names:
                        violations.append(
                            f"{rel}:{node.lineno}: missing answering runtime_state_store="
                        )
                    if "backend" not in keyword_names:
                        violations.append(f"{rel}:{node.lineno}: missing answering backend=")
                elif node.func.id == "SystemApplicationServices":
                    keyword_names = {kw.arg for kw in node.keywords if kw.arg is not None}
                    found_services_bundle = "facade_support" in keyword_names
                    for required in (
                        "operations_service",
                        "answering_service",
                        "facade_support",
                    ):
                        if required not in keyword_names:
                            violations.append(
                                f"{rel}:{node.lineno}: missing services bundle {required}="
                            )

        self.assertTrue(
            found_support_call,
            "application service composer should construct SystemFacadeSupport",
        )
        self.assertTrue(
            found_operations_call,
            "application service composer should construct SystemOperationsService",
        )
        self.assertTrue(
            found_answering_call,
            "application service composer should construct SystemAnsweringService",
        )
        self.assertTrue(
            found_support_state_store,
            "application service composer should wire runtime_state_store into SystemFacadeSupport",
        )
        self.assertTrue(
            found_operations_manager,
            "application service composer should wire backend into SystemOperationsService",
        )
        self.assertTrue(
            found_answering_state_store,
            "application service composer should wire runtime_state_store into SystemAnsweringService",
        )
        self.assertTrue(
            found_answering_manager,
            "application service composer should wire backend into SystemAnsweringService",
        )
        self.assertTrue(
            found_services_bundle,
            "application service bundle should carry facade_support",
        )
        self.assertFalse(
            violations,
            "Found application-service composer wiring gaps:\n" + "\n".join(violations),
        )

    def test_runtime_manager_uses_runtime_state_store(self) -> None:
        path = RAG_MODULES_DIR / "app" / "composition" / "runtime_manager.py"
        rel = path.relative_to(ROOT)
        source = path.read_text(encoding="utf-8-sig")
        tree = ast.parse(source, filename=str(path))
        lines = source.splitlines()
        found_store_import = False
        found_store_access = False
        violations: list[str] = []

        prohibited = {
            "SystemRuntime",
        }

        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                module_name = self._resolve_import_from(path, node)
                if module_name.endswith("runtime_state_store") and any(
                    alias.name == "RuntimeStateStore" for alias in node.names
                ):
                    found_store_import = True
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "rag_modules.app.composition.runtime_state_store":
                        found_store_import = True
            elif isinstance(node, ast.Call):
                func_name = (
                    node.func.id
                    if isinstance(node.func, ast.Name)
                    else node.func.attr
                    if isinstance(node.func, ast.Attribute)
                    else None
                )
                if func_name in prohibited:
                    violations.append(f"{rel}:{node.lineno}: {lines[node.lineno - 1].strip()}")
            elif isinstance(node, ast.Attribute):
                chain = ".".join(self._attribute_chain(node))
                if chain.startswith("self.runtime_state_store."):
                    found_store_access = True

        self.assertTrue(
            found_store_import,
            "runtime manager should depend on RuntimeStateStore for runtime ownership",
        )
        self.assertTrue(
            found_store_access,
            "runtime manager should delegate runtime ownership to runtime_state_store",
        )
        self.assertFalse(
            violations,
            "Found runtime-manager runtime construction that should live in RuntimeStateStore:\n"
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
            "self.refresh_service.refresh_from_build",
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
            RAG_MODULES_DIR / "app" / "composition" / "runtime_refresh_service.py": {
                "self.serving_bootstrapper.prepare_with_shared_runtime",
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

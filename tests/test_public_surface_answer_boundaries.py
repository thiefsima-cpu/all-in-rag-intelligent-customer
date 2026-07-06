from __future__ import annotations

import tests.public_surface_boundary_helpers as h

ast = h.ast
importlib = h.importlib
Path = h.Path
ROOT = h.ROOT
RAG_MODULES_DIR = h.RAG_MODULES_DIR
APP_COMPOSITION_IMPORT_BOUNDARIES = h.APP_COMPOSITION_IMPORT_BOUNDARIES
APP_COMPOSITION_CALL_BOUNDARIES = h.APP_COMPOSITION_CALL_BOUNDARIES
APP_COMPOSITION_DEFINITION_BOUNDARIES = h.APP_COMPOSITION_DEFINITION_BOUNDARIES
PublicSurfaceBoundaryTestCase = h.PublicSurfaceBoundaryTestCase


class PublicSurfaceAnswerBoundaryTests(PublicSurfaceBoundaryTestCase):
    """Answer, generation, query-understanding, and grouped runtime-view boundaries."""

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


from __future__ import annotations

import tests.public_surface_boundary_helpers as h

ast = h.ast
importlib = h.importlib
ROOT = h.ROOT
RAG_MODULES_DIR = h.RAG_MODULES_DIR
ALLOWED_ROOT_WRAPPERS = h.ALLOWED_ROOT_WRAPPERS
MIGRATED_ROOT_SHARED_MODULE_FILES = h.MIGRATED_ROOT_SHARED_MODULE_FILES
PROHIBITED_LEGACY_FACADE_MODULES = h.PROHIBITED_LEGACY_FACADE_MODULES
PublicSurfaceBoundaryTestCase = h.PublicSurfaceBoundaryTestCase


class PublicSurfaceDependencyBoundaryTests(PublicSurfaceBoundaryTestCase):
    """Package dependency, facade, and domain contract boundaries."""

    def test_migrated_shared_modules_are_not_at_rag_modules_root(self) -> None:
        remaining = {
            path.name
            for path in RAG_MODULES_DIR.glob("*.py")
            if path.name in MIGRATED_ROOT_SHARED_MODULE_FILES
        }

        self.assertEqual(set(), remaining)

    def test_api_modules_do_not_import_build_job_runtime_or_composition_adapters(self) -> None:
        prohibited_modules = {
            "rag_modules.app.composition",
            "rag_modules.runtime.build_jobs",
        }
        violations: list[str] = []

        for path in (RAG_MODULES_DIR / "interfaces" / "api").rglob("*.py"):
            lines = path.read_text(encoding="utf-8-sig").splitlines()
            for lineno, _line, module_name, imported_name in self._iter_resolved_imports(path):
                if self._module_matches(module_name, prohibited_modules) or self._module_matches(
                    imported_name,
                    prohibited_modules,
                ):
                    violations.append(
                        self._violation(
                            path,
                            lineno,
                            lines,
                            "API must depend on build-job application ports and assembly only",
                        )
                    )

        self.assertFalse(
            violations,
            "Found API imports of build-job runtime/composition adapters:\n"
            + "\n".join(violations),
        )

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

    def test_application_layer_depends_only_on_contracts_kernel_and_safe_utilities(self) -> None:
        application_dir = RAG_MODULES_DIR / "application"
        allowed_modules = {
            "rag_modules.application",
            "rag_modules.contracts",
            "rag_modules.kernel",
            "rag_modules.safe_logging",
        }
        violations: list[str] = []

        self.assertTrue(application_dir.is_dir(), "rag_modules/application package is missing")
        for path in application_dir.rglob("*.py"):
            rel = path.relative_to(ROOT)
            for lineno, line, module_name, _imported_name in self._iter_resolved_imports(path):
                if module_name.startswith("rag_modules.") and not self._module_matches(
                    module_name,
                    allowed_modules,
                ):
                    violations.append(f"{rel}:{lineno}: {line}")

        self.assertFalse(
            violations,
            "Application use cases must receive feature implementations from composition:\n"
            + "\n".join(violations),
        )

    def test_application_use_cases_do_not_construct_feature_workflows_or_factories(self) -> None:
        answer_source = (
            RAG_MODULES_DIR / "application" / "answering" / "answer_workflow.py"
        ).read_text(encoding="utf-8-sig")
        knowledge_base_source = (RAG_MODULES_DIR / "application" / "knowledge_base.py").read_text(
            encoding="utf-8-sig"
        )

        self.assertNotIn("RetrievalRuntimeProfileFactory", answer_source)
        self.assertNotIn("KnowledgeBaseBuildWorkflow(", knowledge_base_source)

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
        old_matcher_import = "rag_modules.contracts.query_constraints.RecipeConstraintMatcher"

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

    def test_runtime_model_dependencies_are_one_way(self) -> None:
        path = RAG_MODULES_DIR / "contracts" / "runtime" / "retrieval.py"
        tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
        imports = {
            self._resolve_import_from(path, node)
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
        }
        self.assertNotIn("rag_modules.contracts.runtime.workflows", imports)

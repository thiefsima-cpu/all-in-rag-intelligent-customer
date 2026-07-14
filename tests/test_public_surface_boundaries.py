from __future__ import annotations

import tests.public_surface_boundary_helpers as h

ast = h.ast
importlib = h.importlib
re = h.re
sys = h.sys
tomllib = h.tomllib
API_PREFIX = h.API_PREFIX
API_VERSION = h.API_VERSION
EXTERNAL_PUBLIC_SURFACE = h.EXTERNAL_PUBLIC_SURFACE
LEGACY_PUBLIC_SURFACE = h.LEGACY_PUBLIC_SURFACE
LEGACY_PUBLIC_SURFACE_REMOVAL_VERSION = h.LEGACY_PUBLIC_SURFACE_REMOVAL_VERSION
LEGACY_PUBLIC_SURFACE_SCAN_RULES = h.LEGACY_PUBLIC_SURFACE_SCAN_RULES
ROOT_PUBLIC_SURFACE = h.ROOT_PUBLIC_SURFACE
ROOT = h.ROOT
RAG_MODULES_DIR = h.RAG_MODULES_DIR
ALLOWED_ROOT_WRAPPERS = h.ALLOWED_ROOT_WRAPPERS
RETIRED_LEGACY_FACADE_MODULES = h.RETIRED_LEGACY_FACADE_MODULES
RETIRED_LATE_MIGRATION_COMPAT_EXPORTS = h.RETIRED_LATE_MIGRATION_COMPAT_EXPORTS
RETIRED_INTERNAL_COMPAT_SHELLS = h.RETIRED_INTERNAL_COMPAT_SHELLS
RETIRED_INTERNAL_COMPAT_NAMES = h.RETIRED_INTERNAL_COMPAT_NAMES
RETIRED_PROVIDER_COMPONENTS_PACKAGE = h.RETIRED_PROVIDER_COMPONENTS_PACKAGE
RETIRED_PROVIDER_COMPONENTS_PATH = h.RETIRED_PROVIDER_COMPONENTS_PATH
RETIRED_PROVIDER_COMPONENTS_MODULES = h.RETIRED_PROVIDER_COMPONENTS_MODULES
MISLEADING_COMPAT_DOCSTRING_PATTERNS = h.MISLEADING_COMPAT_DOCSTRING_PATTERNS
PublicSurfaceBoundaryTestCase = h.PublicSurfaceBoundaryTestCase


class PublicSurfaceLegacyBoundaryTests(PublicSurfaceBoundaryTestCase):
    """Public manifest, version governance, and retired facade boundaries."""

    def test_package_version_parser_accepts_release_candidate_and_development_versions(
        self,
    ) -> None:
        self.assertEqual(self._version_tuple("0.4.0rc1"), (0, 4, 0))
        self.assertEqual(self._version_tuple("0.4.0.dev0"), (0, 4, 0))

    def assert_document_contains_any(
        self,
        document: str,
        expected_options: tuple[str, ...],
        *,
        context: str,
    ) -> None:
        if any(expected in document for expected in expected_options):
            return

        self.fail(f"{context} must contain one of: {expected_options!r}")

    def test_retirement_plan_document_states_current_policy(self) -> None:
        plan_path = ROOT / "docs" / "public_surface_retirement_plan.md"
        self.assertTrue(plan_path.exists())
        content = plan_path.read_text(encoding="utf-8")

        for heading in (
            "## Current Policy",
            "## Canonical Packages",
            "## Root Package Exports",
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
        self.assertNotIn("rag_modules.runtime_contracts", content)
        self.assertNotIn("rag_modules.app.runtime_contracts", content)
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
            "Root package exports are public API",
            "rag_modules.__all__",
            "ROOT_PACKAGE_EXPORTS",
            "root wrapper modules remain retired",
            "rag_modules.graph.cache",
            "rag_modules.graph.evidence",
            "rag_modules.graph.query",
            "rag_modules.graph.reasoning",
            "rag_modules.graph.retrieval",
            "rag_modules.interfaces.api.routes",
        ):
            self.assertIn(expected, content)

    def test_version_governance_distinguishes_package_api_and_compat_versions(self) -> None:
        with (ROOT / "pyproject.toml").open("rb") as file:
            package_version = tomllib.load(file)["project"]["version"]
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        policy = (ROOT / "docs" / "public_surface_retirement_plan.md").read_text(encoding="utf-8")
        normalized_readme = " ".join(readme.split())
        normalized_policy = " ".join(policy.split())

        self.assertIn(f"current package version is `{package_version}`", normalized_policy)

        for context, expected_options in (
            ("version governance heading", ("## Version Governance", "## 版本治理")),
            (
                "package version",
                (f"Package version: `{package_version}`", f"包版本：`{package_version}`"),
            ),
            ("API version", (f"API version: `{API_VERSION}`", f"API 版本：`{API_VERSION}`")),
            ("API prefix", (f"API prefix: `{API_PREFIX}`", f"API 前缀是 `{API_PREFIX}`")),
            (
                "compatibility removal version",
                (
                    f"Compatibility removal version: `{LEGACY_PUBLIC_SURFACE_REMOVAL_VERSION}`",
                    f"兼容性移除版本：`{LEGACY_PUBLIC_SURFACE_REMOVAL_VERSION}`",
                ),
            ),
            (
                "package/API version independence",
                (
                    "Package releases can keep the same API version",
                    "包发布可以保持相同 API 版本",
                ),
            ),
            (
                "compatibility removal axis",
                (
                    "Compatibility removals must name their version axis",
                    "必须明确版本轴",
                ),
            ),
        ):
            with self.subTest(context=context):
                self.assert_document_contains_any(
                    normalized_readme,
                    expected_options,
                    context=context,
                )

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

        for expected in (
            "rag_modules.application",
            "rag_modules.app.services",
            "directly call resolved composition collaborators",
            "Do not add forwarding-only modules",
        ):
            self.assertIn(expected, guide)

        for expected in (
            "rag_modules.application.*",
            "rag_modules.app.diagnostics",
            "rag_modules.app.services.answer_*",
            "rag_modules.runtime.snapshot_utils",
        ):
            self.assertIn(expected, policy)

        self.assertIn("app_composition_maintenance_guide.md", architecture)
        self.assertIn("rag_modules.app.provider_components", policy)
        self.assertIn("ServingRuntimeRefreshService", policy)

    def test_active_compatibility_layers_are_retired_in_docs(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        policy = (ROOT / "docs" / "public_surface_retirement_plan.md").read_text(encoding="utf-8")
        normalized_readme = " ".join(readme.split())

        self.assert_document_contains_any(
            normalized_readme,
            ("Use `/v1` for new API clients", "新 API client 应使用 `/v1`"),
            context="new clients use versioned API prefix",
        )
        self.assert_document_contains_any(
            normalized_readme,
            (
                "Unversioned serving and build routes are retired",
                "未版本化的服务和构建路由已经退役",
            ),
            context="unversioned serving and build routes are retired",
        )
        for retired_phrase in (
            "compatibility aliases during the migration window",
            "迁移窗口期间的兼容性别名",
        ):
            self.assertNotIn(retired_phrase, readme)

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
        paths = tuple(
            RAG_MODULES_DIR / "interfaces" / "api" / filename
            for filename in ("build_routes.py", "operational_routes.py", "serving_routes.py")
        )
        sources: list[str] = []
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

        for path in paths:
            source = path.read_text(encoding="utf-8-sig")
            sources.append(source)
            tree = ast.parse(source, filename=str(path))
            for node in ast.walk(tree):
                if not isinstance(node, ast.FunctionDef):
                    continue
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
                    if kind == "unversioned":
                        violations.append(f"{path.name}:{node.name}: {parsed}")

        self.assertEqual(
            [],
            violations,
            "API route decorators must use canonical /v1 paths only.",
        )
        self.assertNotIn("_versioned_alias_route", "\n".join(sources))

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
            RAG_MODULES_DIR / "neo4j_pool.py",
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

    def test_internal_facade_docstrings_do_not_claim_compatibility_shims(self) -> None:
        violations: list[str] = []

        for path in RAG_MODULES_DIR.rglob("*.py"):
            rel = path.relative_to(ROOT)
            source = path.read_text(encoding="utf-8-sig")
            tree = ast.parse(source, filename=str(path))

            docstrings: list[tuple[int, str]] = []
            module_docstring = ast.get_docstring(tree, clean=False)
            if module_docstring and tree.body:
                docstrings.append((tree.body[0].lineno, module_docstring))

            for node in ast.walk(tree):
                if not isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                docstring = ast.get_docstring(node, clean=False)
                if docstring:
                    docstrings.append((node.lineno, docstring))

            for lineno, docstring in docstrings:
                if any(
                    pattern.search(docstring) for pattern in MISLEADING_COMPAT_DOCSTRING_PATTERNS
                ):
                    summary = docstring.splitlines()[0]
                    violations.append(f"{rel}:{lineno}: {summary}")

        self.assertFalse(
            violations,
            "Found internal facade/export docstrings that still claim compatibility-shim status:\n"
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

    def test_canonical_facade_modules_are_thin_exports(self) -> None:
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
            "Found canonical facade modules with local logic:\n" + "\n".join(violations),
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

from __future__ import annotations

import tests.public_surface_boundary_helpers as h

ast = h.ast
ROOT = h.ROOT
RAG_MODULES_DIR = h.RAG_MODULES_DIR
APP_COMPOSITION_IMPORT_BOUNDARIES = h.APP_COMPOSITION_IMPORT_BOUNDARIES
APP_COMPOSITION_CALL_BOUNDARIES = h.APP_COMPOSITION_CALL_BOUNDARIES
APP_COMPOSITION_DYNAMIC_LOOKUP_BOUNDARIES = h.APP_COMPOSITION_DYNAMIC_LOOKUP_BOUNDARIES
APP_COMPOSITION_ATTRIBUTE_BOUNDARIES = h.APP_COMPOSITION_ATTRIBUTE_BOUNDARIES
PublicSurfaceBoundaryTestCase = h.PublicSurfaceBoundaryTestCase


class PublicSurfaceRuntimeBoundaryTests(PublicSurfaceBoundaryTestCase):
    """Application composition, bootstrapper, runtime manager, and lifecycle boundaries."""

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

    def test_public_bootstrapper_facades_bind_only_typed_composer_results(self) -> None:
        path = RAG_MODULES_DIR / "app" / "bootstrap.py"
        rel = path.relative_to(ROOT)
        source = path.read_text(encoding="utf-8-sig")
        tree = ast.parse(source, filename=str(path))
        lines = source.splitlines()
        violations: list[str] = []
        assignments: set[tuple[str, str]] = set()

        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                value_chain = ".".join(self._attribute_chain(node.value))
                for target in node.targets:
                    target_chain = ".".join(self._attribute_chain(target))
                    if not target_chain.startswith("self."):
                        continue
                    if value_chain.startswith("components."):
                        assignments.add((target_chain, value_chain))
                        if target_chain.removeprefix("self.") != value_chain.removeprefix(
                            "components."
                        ):
                            violations.append(
                                f"{rel}:{node.lineno}: {lines[node.lineno - 1].strip()}"
                            )
            elif isinstance(node, ast.Call):
                call_name = self._call_name(node)
                if call_name in {"getattr", "setattr", "vars", "fields", "is_dataclass"}:
                    violations.append(f"{rel}:{node.lineno}: {lines[node.lineno - 1].strip()}")
                if not isinstance(node.func, ast.Attribute):
                    continue
                if ".".join(self._attribute_chain(node.func)) == "object.__getattribute__":
                    violations.append(f"{rel}:{node.lineno}: {lines[node.lineno - 1].strip()}")

        expected_assignments = {
            ("self.provider", "components.provider"),
            ("self.factory", "components.factory"),
            ("self.executor", "components.executor"),
            ("self.preparer", "components.preparer"),
            ("self.lifecycle_service", "components.lifecycle_service"),
            ("self.build_bootstrapper", "components.build_bootstrapper"),
            ("self.serving_bootstrapper", "components.serving_bootstrapper"),
            ("self.bootstrap_service", "components.bootstrap_service"),
        }

        self.assertFalse(
            violations,
            "Found dynamic or mismatched public bootstrapper component binding:\n"
            + "\n".join(violations),
        )
        self.assertEqual(assignments, expected_assignments)

    def test_public_bootstrappers_call_resolved_runtime_collaborators_directly(self) -> None:
        path = RAG_MODULES_DIR / "app" / "bootstrap.py"
        source = path.read_text(encoding="utf-8-sig")

        for expected in (
            "self.factory.build(",
            "self.executor.build_knowledge_base(",
            "self.executor.rebuild_knowledge_base(",
            "self.lifecycle_service.build_ready(",
            "self.lifecycle_service.prepare(",
            "self.lifecycle_service.prepare_with_shared_runtime(",
            "self.bootstrap_service.build(",
        ):
            self.assertIn(expected, source)
        self.assertNotIn("_invocations", source)
        self.assertNotIn("InvocationAdapter", source)
        self.assertNotIn("_ComposedBootstrapperFacade", source)
        self.assertNotIn("getattr(", source)

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

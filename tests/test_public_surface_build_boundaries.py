from __future__ import annotations

import tests.public_surface_boundary_helpers as h

ast = h.ast
ROOT = h.ROOT
RAG_MODULES_DIR = h.RAG_MODULES_DIR
PublicSurfaceBoundaryTestCase = h.PublicSurfaceBoundaryTestCase


class PublicSurfaceBuildBoundaryTests(PublicSurfaceBoundaryTestCase):
    """Build lifecycle and build workflow public-surface boundaries."""

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


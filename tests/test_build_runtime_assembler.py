from __future__ import annotations

import unittest
from types import SimpleNamespace

from rag_modules.app.composition.build_runtime_assembler import BuildRuntimeAssembler
from rag_modules.runtime.artifacts import ArtifactManifest


class _FakeKnowledgeBaseService:
    def __init__(self, manifest: ArtifactManifest) -> None:
        self.artifact_manifest = manifest


class _CapturingServicesProvider:
    def __init__(self, knowledge_base_service) -> None:
        self.knowledge_base_service = knowledge_base_service
        self.calls: list[dict] = []

    def provide_knowledge_base_service(self, **kwargs):
        self.calls.append(kwargs)
        return self.knowledge_base_service


class _CapturingDiagnosticsProvider:
    def __init__(self, runtime_stats_access) -> None:
        self.runtime_stats_access = runtime_stats_access
        self.calls: list[dict] = []

    def provide_runtime_stats_access(self, **kwargs):
        self.calls.append(kwargs)
        return self.runtime_stats_access


class _CapturingBuildPipelineProvider:
    def __init__(self, *, document_artifact_builder, semantic_graph_schema_sync) -> None:
        self.document_artifact_builder = document_artifact_builder
        self.semantic_graph_schema_sync = semantic_graph_schema_sync
        self.document_builder_calls: list[dict] = []
        self.schema_sync_calls: list[dict] = []

    def provide_document_artifact_builder(self, **kwargs):
        self.document_builder_calls.append(kwargs)
        return self.document_artifact_builder

    def provide_semantic_graph_schema_sync(self, **kwargs):
        self.schema_sync_calls.append(kwargs)
        return self.semantic_graph_schema_sync


class BuildRuntimeAssemblerTests(unittest.TestCase):
    def test_assembler_injects_build_lifecycle_ports_and_services(self) -> None:
        manifest_store = object()
        document_artifact_cache = object()
        runtime_artifact_access = object()
        runtime_stats_access = object()
        document_artifact_builder = object()
        semantic_graph_schema_sync = object()
        knowledge_base_service = _FakeKnowledgeBaseService(
            ArtifactManifest.missing(manifest_path="manifest.json")
        )
        services = _CapturingServicesProvider(knowledge_base_service)
        diagnostics = _CapturingDiagnosticsProvider(runtime_stats_access)
        build_pipeline = _CapturingBuildPipelineProvider(
            document_artifact_builder=document_artifact_builder,
            semantic_graph_schema_sync=semantic_graph_schema_sync,
        )
        graph_manager = SimpleNamespace(name="graph")
        data_module = SimpleNamespace(name="data")
        index_module = SimpleNamespace(name="index")
        infrastructure = SimpleNamespace(
            provide_neo4j_manager=lambda config, existing=None: existing or graph_manager,
            provide_data_module=(
                lambda config, neo4j_manager, existing=None: existing or data_module
            ),
            provide_index_module=lambda config, existing=None: existing or index_module,
            provide_artifact_manifest_store=(
                lambda config, existing=None: existing or manifest_store
            ),
            provide_document_artifact_cache=(
                lambda config, existing=None, *, manifest_store=None: (
                    existing or document_artifact_cache
                )
            ),
            provide_runtime_artifact_access=(
                lambda config, existing=None: existing or runtime_artifact_access
            ),
        )
        assembler = BuildRuntimeAssembler(
            provider=SimpleNamespace(
                infrastructure=infrastructure,
                diagnostics=diagnostics,
                build_pipeline=build_pipeline,
                services=services,
            )
        )

        runtime = assembler.assemble(config=SimpleNamespace())

        self.assertIs(runtime.knowledge_base_service, knowledge_base_service)
        self.assertEqual(len(services.calls), 1)
        self.assertIs(services.calls[0]["manifest_store"], manifest_store)
        self.assertIs(services.calls[0]["runtime_artifact_access"], runtime_artifact_access)
        self.assertIs(services.calls[0]["runtime_stats_access"], runtime_stats_access)
        self.assertIs(services.calls[0]["document_artifact_builder"], document_artifact_builder)
        self.assertIs(services.calls[0]["semantic_graph_schema_sync"], semantic_graph_schema_sync)
        self.assertEqual(len(diagnostics.calls), 1)
        self.assertEqual(len(build_pipeline.document_builder_calls), 1)
        self.assertIs(build_pipeline.document_builder_calls[0]["manifest_store"], manifest_store)
        self.assertIs(build_pipeline.document_builder_calls[0]["cache"], document_artifact_cache)
        self.assertEqual(len(build_pipeline.schema_sync_calls), 1)
        self.assertIs(build_pipeline.schema_sync_calls[0]["neo4j_manager"], graph_manager)
        self.assertIs(runtime.artifact_manifest, knowledge_base_service.artifact_manifest)


if __name__ == "__main__":
    unittest.main()

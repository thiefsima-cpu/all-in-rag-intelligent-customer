from __future__ import annotations

import unittest

from rag_modules.artifacts import ArtifactManifest
from rag_modules.build_pipeline.contracts import SemanticGraphSchemaSyncResult
from rag_modules.build_pipeline.document_artifacts.models import DocumentArtifactResult
from rag_modules.build_pipeline.knowledge_base_workflow import KnowledgeBaseBuildWorkflow
from rag_modules.configuration.testing import build_test_config
from rag_modules.text_document import TextDocument


class _FakeManifestStore:
    def __init__(self, manifest: ArtifactManifest) -> None:
        self.manifest = manifest
        self.load_calls = 0
        self.saved: list[ArtifactManifest] = []

    def load(self) -> ArtifactManifest:
        self.load_calls += 1
        return self.manifest

    def save(self, manifest: ArtifactManifest) -> ArtifactManifest:
        self.manifest = manifest
        self.saved.append(manifest)
        return manifest


class _FakeRuntimeArtifactAccess:
    def __init__(self) -> None:
        self.graph_load_calls = 0
        self.vector_has_collection_calls = 0
        self.vector_load_calls = 0
        self.vector_build_calls = 0
        self.vector_delete_calls = 0

    def load_graph_data(self, data_module):
        self.graph_load_calls += 1
        return data_module.load_graph_data()

    def has_vector_collection(self, index_module) -> bool:
        self.vector_has_collection_calls += 1
        return bool(index_module.has_collection())

    def load_vector_collection(self, index_module) -> bool:
        self.vector_load_calls += 1
        return bool(index_module.load_collection())

    def build_vector_index(self, index_module, chunks) -> bool:
        self.vector_build_calls += 1
        return bool(index_module.build_vector_index(chunks))

    def delete_vector_collection(self, index_module) -> bool:
        self.vector_delete_calls += 1
        return bool(index_module.delete_collection())


class _FakeRuntimeStatsAccess:
    def __init__(self) -> None:
        self.graph_stats_calls = 0
        self.vector_stats_calls = 0
        self.route_stats_calls = 0

    def get_graph_data_stats(self, data_module) -> dict:
        self.graph_stats_calls += 1
        return dict(data_module.get_statistics() or {})

    def get_vector_collection_stats(self, index_module) -> dict:
        self.vector_stats_calls += 1
        return dict(index_module.get_collection_stats() or {})

    def get_route_stats(self, query_router) -> dict:
        self.route_stats_calls += 1
        if query_router is None:
            return {}
        return dict(query_router.get_route_statistics() or {})

    def get_retrieval_runtime_profile(self, retrieval_runtime_profile) -> dict:
        del retrieval_runtime_profile
        return {}


class _FakeDocumentArtifactBuilder:
    def __init__(self, result: DocumentArtifactResult) -> None:
        self.result = result
        self.calls = 0

    def build_or_load(self, data_module):
        self.calls += 1
        return self.result


class _FakeSemanticGraphSchemaSync:
    def __init__(self, result: SemanticGraphSchemaSyncResult) -> None:
        self.result = result
        self.calls = 0

    def sync_from_documents(self, documents) -> SemanticGraphSchemaSyncResult:
        self.calls += 1
        return self.result


class KnowledgeBaseBuildWorkflowTests(unittest.TestCase):
    def test_build_existing_collection_uses_runtime_artifact_access(self) -> None:
        config = build_test_config(
            {
                "graph": {
                    "enable_semantic_graph_schema": False,
                }
            }
        )
        persisted_manifest = ArtifactManifest(
            stage="ready",
            manifest_path="manifest.json",
            index_signature="sig-1",
        )
        manifest_store = _FakeManifestStore(persisted_manifest)
        runtime_artifact_access = _FakeRuntimeArtifactAccess()
        runtime_stats_access = _FakeRuntimeStatsAccess()
        data_module = type("DataModule", (), {})()
        data_module.graph_load_calls = 0
        data_module.documents = [TextDocument(content="doc")]
        data_module.get_statistics = lambda: {"total_recipes": 1, "total_chunks": 1}

        def _load_graph_data():
            data_module.graph_load_calls += 1

        data_module.load_graph_data = _load_graph_data
        index_module = type("IndexModule", (), {})()
        index_module.has_collection = lambda: True
        index_module.load_collection = lambda: True
        index_module.get_collection_stats = lambda: {"row_count": 7}
        workflow = KnowledgeBaseBuildWorkflow(
            config=config,
            neo4j_manager=None,
            data_module=data_module,
            index_module=index_module,
            manifest_store=manifest_store,
            runtime_artifact_access=runtime_artifact_access,
            runtime_stats_access=runtime_stats_access,
        )
        document_result = DocumentArtifactResult(
            documents=[TextDocument(content="doc")],
            chunks=[TextDocument(content="chunk")],
            manifest=ArtifactManifest(
                stage="documents_ready",
                manifest_path="manifest.json",
                index_signature="sig-1",
            ),
            cache_hit=True,
        )
        document_artifact_builder = _FakeDocumentArtifactBuilder(document_result)
        semantic_graph_schema_sync = _FakeSemanticGraphSchemaSync(
            SemanticGraphSchemaSyncResult(enabled=False)
        )
        workflow.document_artifact_builder = document_artifact_builder
        workflow.semantic_graph_schema_sync = semantic_graph_schema_sync
        manifest = workflow.build()

        self.assertTrue(manifest.is_ready)
        self.assertEqual(manifest_store.load_calls, 1)
        self.assertEqual(runtime_artifact_access.vector_has_collection_calls, 1)
        self.assertEqual(runtime_artifact_access.vector_load_calls, 1)
        self.assertEqual(runtime_artifact_access.graph_load_calls, 1)
        self.assertEqual(runtime_stats_access.vector_stats_calls, 1)
        self.assertEqual(runtime_stats_access.graph_stats_calls, 0)
        self.assertEqual(runtime_stats_access.route_stats_calls, 0)
        self.assertEqual(document_artifact_builder.calls, 1)
        self.assertEqual(semantic_graph_schema_sync.calls, 0)
        self.assertEqual(data_module.graph_load_calls, 1)
        self.assertEqual(manifest.vector_rows, 7)
        self.assertEqual(manifest.build_metadata.get("document_cache_hit"), True)
        self.assertEqual(
            manifest.build_metadata.get("config_profile", {}).get("name"),
            config.profile_name,
        )

    def test_build_new_collection_uses_runtime_artifact_access_for_index_lifecycle(self) -> None:
        config = build_test_config(
            {
                "graph": {
                    "enable_semantic_graph_schema": False,
                }
            }
        )
        manifest_store = _FakeManifestStore(ArtifactManifest.missing(manifest_path="manifest.json"))
        runtime_artifact_access = _FakeRuntimeArtifactAccess()
        runtime_stats_access = _FakeRuntimeStatsAccess()
        document_result = DocumentArtifactResult(
            documents=[TextDocument(content="doc")],
            chunks=[TextDocument(content="chunk")],
            manifest=ArtifactManifest.missing(manifest_path="manifest.json"),
            cache_hit=False,
        )
        document_artifact_builder = _FakeDocumentArtifactBuilder(document_result)
        semantic_graph_schema_sync = _FakeSemanticGraphSchemaSync(
            SemanticGraphSchemaSyncResult(enabled=False)
        )
        data_module = type("DataModule", (), {})()
        data_module.documents = [TextDocument(content="doc")]
        data_module.get_statistics = lambda: {"total_recipes": 1, "total_chunks": 1}
        data_module.load_graph_data = lambda: None
        index_module = type("IndexModule", (), {})()
        index_module.has_collection = lambda: False
        index_module.load_collection = lambda: False
        index_module.build_vector_index = lambda chunks: True
        index_module.delete_collection = lambda: True
        index_module.get_collection_stats = lambda: {"row_count": 3}
        workflow = KnowledgeBaseBuildWorkflow(
            config=config,
            neo4j_manager=None,
            data_module=data_module,
            index_module=index_module,
            manifest_store=manifest_store,
            runtime_artifact_access=runtime_artifact_access,
            runtime_stats_access=runtime_stats_access,
            document_artifact_builder=document_artifact_builder,
            semantic_graph_schema_sync=semantic_graph_schema_sync,
        )

        manifest = workflow.build()

        self.assertTrue(manifest.is_ready)
        self.assertEqual(runtime_artifact_access.vector_has_collection_calls, 1)
        self.assertEqual(runtime_artifact_access.vector_build_calls, 1)
        self.assertEqual(runtime_stats_access.graph_stats_calls, 1)
        self.assertGreaterEqual(runtime_stats_access.vector_stats_calls, 1)
        self.assertEqual(runtime_stats_access.route_stats_calls, 1)

    def test_build_metadata_includes_config_profile(self) -> None:
        config = build_test_config({"retrieval": {"top_k": 4}})
        config.profile_name = "eval_fast"
        config.profile_path = "profiles/eval_fast.toml"
        config.profile_hash = "abc123"
        manifest_store = _FakeManifestStore(ArtifactManifest.missing(manifest_path="manifest.json"))
        runtime_artifact_access = _FakeRuntimeArtifactAccess()
        runtime_stats_access = _FakeRuntimeStatsAccess()
        document_result = DocumentArtifactResult(
            documents=[TextDocument(content="doc")],
            chunks=[TextDocument(content="chunk")],
            manifest=ArtifactManifest.missing(manifest_path="manifest.json"),
            cache_hit=False,
        )
        data_module = type("DataModule", (), {})()
        data_module.documents = [TextDocument(content="doc")]
        data_module.get_statistics = lambda: {"total_recipes": 1, "total_chunks": 1}
        data_module.load_graph_data = lambda: None
        index_module = type("IndexModule", (), {})()
        index_module.has_collection = lambda: False
        index_module.load_collection = lambda: False
        index_module.build_vector_index = lambda chunks: True
        index_module.delete_collection = lambda: True
        index_module.get_collection_stats = lambda: {"row_count": 3}
        workflow = KnowledgeBaseBuildWorkflow(
            config=config,
            neo4j_manager=None,
            data_module=data_module,
            index_module=index_module,
            manifest_store=manifest_store,
            runtime_artifact_access=runtime_artifact_access,
            runtime_stats_access=runtime_stats_access,
            document_artifact_builder=_FakeDocumentArtifactBuilder(document_result),
            semantic_graph_schema_sync=_FakeSemanticGraphSchemaSync(
                SemanticGraphSchemaSyncResult(enabled=False)
            ),
        )

        manifest = workflow.build()

        self.assertEqual(
            manifest.build_metadata["config_profile"],
            {
                "name": "eval_fast",
                "path": "profiles/eval_fast.toml",
                "hash": "abc123",
            },
        )

    def test_build_existing_collection_rebuilds_when_index_signature_changes(self) -> None:
        config = build_test_config(
            {
                "graph": {
                    "enable_semantic_graph_schema": False,
                }
            }
        )
        manifest_store = _FakeManifestStore(
            ArtifactManifest(
                stage="ready",
                manifest_path="manifest.json",
                index_signature="stale-index",
            )
        )
        runtime_artifact_access = _FakeRuntimeArtifactAccess()
        runtime_stats_access = _FakeRuntimeStatsAccess()
        document_result = DocumentArtifactResult(
            documents=[TextDocument(content="doc")],
            chunks=[TextDocument(content="chunk")],
            manifest=ArtifactManifest(
                stage="documents_ready",
                manifest_path="manifest.json",
                index_signature="fresh-index",
            ),
            cache_hit=True,
        )
        document_artifact_builder = _FakeDocumentArtifactBuilder(document_result)
        data_module = type("DataModule", (), {})()
        data_module.documents = [TextDocument(content="doc")]
        data_module.get_statistics = lambda: {"total_recipes": 1, "total_chunks": 1}
        data_module.load_graph_data = lambda: None
        index_module = type("IndexModule", (), {})()
        index_module.has_collection = lambda: True
        index_module.load_collection = lambda: True
        index_module.build_vector_index = lambda chunks: True
        index_module.get_collection_stats = lambda: {"row_count": 3}
        workflow = KnowledgeBaseBuildWorkflow(
            config=config,
            neo4j_manager=None,
            data_module=data_module,
            index_module=index_module,
            manifest_store=manifest_store,
            runtime_artifact_access=runtime_artifact_access,
            runtime_stats_access=runtime_stats_access,
            document_artifact_builder=document_artifact_builder,
            semantic_graph_schema_sync=_FakeSemanticGraphSchemaSync(
                SemanticGraphSchemaSyncResult(enabled=False)
            ),
        )

        manifest = workflow.build()

        self.assertTrue(manifest.is_ready)
        self.assertEqual(runtime_artifact_access.vector_has_collection_calls, 1)
        self.assertEqual(runtime_artifact_access.vector_load_calls, 0)
        self.assertEqual(runtime_artifact_access.vector_build_calls, 1)
        self.assertEqual(manifest.index_signature, "fresh-index")


if __name__ == "__main__":
    unittest.main()

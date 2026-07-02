from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from rag_modules.build_pipeline.contracts import SemanticGraphSchemaSyncResult
from rag_modules.build_pipeline.document_artifacts.models import DocumentArtifactResult
from rag_modules.build_pipeline.knowledge_base_workflow import KnowledgeBaseBuildWorkflow
from rag_modules.configuration.testing import build_test_config
from rag_modules.infra.milvus_index_construction import MilvusIndexConstructionModule
from rag_modules.runtime.artifacts import (
    ARTIFACT_STAGE_MANIFEST_UNREADABLE,
    ArtifactManifest,
    ArtifactManifestStore,
)
from rag_modules.text_document import TextDocument


class _FakeMilvusClient:
    def __init__(self) -> None:
        self.collections = {"recipes__blue", "recipes__green"}
        self.aliases: dict[str, str] = {}
        self.created_aliases: list[tuple[str, str]] = []
        self.altered_aliases: list[tuple[str, str]] = []

    def has_collection(self, collection_name: str) -> bool:
        return collection_name in self.collections

    def create_alias(self, *, collection_name: str, alias: str) -> None:
        self.aliases[alias] = collection_name
        self.created_aliases.append((alias, collection_name))

    def alter_alias(self, *, collection_name: str, alias: str) -> None:
        self.aliases[alias] = collection_name
        self.altered_aliases.append((alias, collection_name))

    def drop_alias(self, *, alias: str) -> None:
        self.aliases.pop(alias, None)

    def describe_alias(self, *, alias: str) -> dict:
        if alias not in self.aliases:
            raise RuntimeError("alias missing")
        return {"alias": alias, "collection": self.aliases[alias]}

    def drop_collection(self, collection_name: str) -> None:
        self.collections.discard(collection_name)


def _build_index_module(client: _FakeMilvusClient) -> MilvusIndexConstructionModule:
    module = MilvusIndexConstructionModule.__new__(MilvusIndexConstructionModule)
    module.client = client
    module.base_collection_name = "recipes"
    module.collection_name = "recipes"
    module.collection_alias = "recipes__active"
    module.blue_green_enabled = True
    module.active_collection_name = ""
    module.active_collection_slot = ""
    module.build_collection_name = ""
    module.collection_created = False
    return module


class _ManifestStore:
    def __init__(self, manifest: ArtifactManifest) -> None:
        self.manifest = manifest
        self.candidate: ArtifactManifest | None = None

    def load(self) -> ArtifactManifest:
        return self.manifest

    def save(self, manifest: ArtifactManifest) -> ArtifactManifest:
        self.manifest = manifest
        return manifest

    def save_candidate(self, manifest: ArtifactManifest) -> ArtifactManifest:
        self.candidate = manifest
        return manifest

    def clear_candidate(self) -> None:
        self.candidate = None


class _DocumentBuilder:
    def __init__(self, result: DocumentArtifactResult) -> None:
        self.result = result

    def build_or_load(self, data_module) -> DocumentArtifactResult:
        return self.result


class _RuntimeStats:
    def get_graph_data_stats(self, data_module) -> dict:
        return {"total_chunks": 1}

    def get_vector_collection_stats(self, index_module) -> dict:
        return {"row_count": 1}

    def get_route_stats(self, query_router) -> dict:
        return {}


class _BlueGreenArtifactAccess:
    def __init__(self, *, build_succeeds: bool = True) -> None:
        self.build_succeeds = build_succeeds
        self.published: list[str] = []
        self.discarded: list[str] = []

    def configure_vector_collection(self, index_module, manifest) -> str:
        index_module.collection_name = manifest.collection_name or "recipes"
        return index_module.collection_name

    def has_vector_collection(self, index_module) -> bool:
        return True

    def load_vector_collection(self, index_module) -> bool:
        return True

    def load_graph_data(self, data_module):
        return data_module.load_graph_data()

    def prepare_vector_index_build(self, index_module, active_collection_name="") -> dict:
        return {
            "collection_name": "recipes__green",
            "collection_base_name": "recipes",
            "collection_slot": "green",
        }

    def build_vector_index(self, index_module, chunks, *, collection_name="") -> bool:
        index_module.collection_name = collection_name
        return self.build_succeeds

    def publish_vector_index(self, index_module, collection_name: str) -> str:
        self.published.append(collection_name)
        index_module.collection_name = "recipes__active"
        return "recipes__blue"

    def rollback_vector_index_publish(self, index_module, previous_collection_name="") -> None:
        index_module.collection_name = previous_collection_name

    def discard_vector_index(self, index_module, collection_name: str) -> bool:
        self.discarded.append(collection_name)
        return True


class MilvusBlueGreenTests(unittest.TestCase):
    def test_milvus_canonical_and_compat_imports_match(self) -> None:
        from rag_modules.infra.milvus import (
            MilvusIndexConstructionModule as PackageModule,
        )
        from rag_modules.infra.milvus.module import (
            MilvusIndexConstructionModule as CanonicalModule,
        )
        from rag_modules.infra.milvus_index_construction import (
            MilvusIndexConstructionModule as CompatModule,
        )

        self.assertIs(PackageModule, CanonicalModule)
        self.assertIs(CompatModule, CanonicalModule)

    def test_manifest_store_publishes_atomic_versions_and_keeps_candidate_separate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            manifest_path = Path(tmp_dir) / "artifact_manifest.json"
            store = ArtifactManifestStore(
                SimpleNamespace(
                    storage=SimpleNamespace(
                        artifact_manifest_path=str(manifest_path),
                    )
                )
            )

            first = store.save(
                ArtifactManifest(
                    stage="ready",
                    collection_name="recipes__blue",
                    collection_base_name="recipes",
                    collection_slot="blue",
                )
            )
            candidate = store.save_candidate(
                first.evolve(
                    stage="building",
                    collection_name="recipes__green",
                    collection_slot="green",
                )
            )

            self.assertEqual(first.manifest_version, 1)
            self.assertEqual(store.load().collection_name, "recipes__blue")
            self.assertEqual(store.load_candidate(), candidate)
            self.assertEqual(store.list_versions(), [1])
            self.assertEqual(store.load_version(1).collection_slot, "blue")

            second = store.save(
                candidate.evolve(
                    stage="ready",
                    previous_collection_name="recipes__blue",
                )
            )

            self.assertEqual(second.manifest_version, 2)
            self.assertEqual(store.list_versions(), [1, 2])
            self.assertEqual(store.load().collection_name, "recipes__green")

    def test_manifest_store_load_unreadable_manifest_uses_stable_error_code(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            secret = "customer-token-secret"
            manifest_path = Path(tmp_dir) / "artifact_manifest.json"
            manifest_path.write_text(f'{{"token": "{secret}",', encoding="utf-8")
            store = ArtifactManifestStore(
                SimpleNamespace(
                    storage=SimpleNamespace(
                        artifact_manifest_path=str(manifest_path),
                    )
                )
            )

            manifest = store.load()

        self.assertEqual(manifest.stage, ARTIFACT_STAGE_MANIFEST_UNREADABLE)
        self.assertEqual(manifest.last_error, "MANIFEST_UNREADABLE")
        self.assertNotIn(secret, str(manifest.to_dict()))

    def test_milvus_module_alternates_slots_and_switches_stable_alias(self) -> None:
        client = _FakeMilvusClient()
        module = _build_index_module(client)

        first_target = module.prepare_blue_green_build("")
        previous = module.publish_collection(first_target["collection_name"])
        second_target = module.prepare_blue_green_build(first_target["collection_name"])
        module.publish_collection(second_target["collection_name"])

        self.assertEqual(first_target["collection_slot"], "blue")
        self.assertEqual(previous, "")
        self.assertEqual(second_target["collection_slot"], "green")
        self.assertEqual(client.aliases["recipes__active"], "recipes__green")
        self.assertEqual(module.collection_name, "recipes__active")

    def test_failed_candidate_build_preserves_ready_manifest(self) -> None:
        config = build_test_config({"graph": {"enable_semantic_graph_schema": False}})
        active = ArtifactManifest(
            stage="ready",
            manifest_version=4,
            index_signature="sig-old",
            index_version="v000004-sig-old",
            collection_name="recipes__blue",
            collection_base_name="recipes",
            collection_slot="blue",
        )
        store = _ManifestStore(active)
        access = _BlueGreenArtifactAccess(build_succeeds=False)
        document_result = DocumentArtifactResult(
            documents=[TextDocument(content="doc")],
            chunks=[TextDocument(content="chunk")],
            manifest=ArtifactManifest(
                stage="documents_ready",
                index_signature="sig-new",
                collection_name="recipes",
                collection_base_name="recipes",
            ),
            cache_hit=False,
        )
        data_module = SimpleNamespace(
            documents=[TextDocument(content="doc")],
            load_graph_data=lambda: None,
            get_statistics=lambda: {"total_chunks": 1},
        )
        workflow = KnowledgeBaseBuildWorkflow(
            config=config,
            neo4j_manager=None,
            data_module=data_module,
            index_module=SimpleNamespace(collection_name="recipes"),
            manifest_store=store,
            runtime_artifact_access=access,
            runtime_stats_access=_RuntimeStats(),
            document_artifact_builder=_DocumentBuilder(document_result),
            semantic_graph_schema_sync=SimpleNamespace(
                sync_from_documents=lambda documents: SemanticGraphSchemaSyncResult(enabled=False)
            ),
        )

        with self.assertRaisesRegex(RuntimeError, "Vector index build failed"):
            workflow.rebuild()

        self.assertEqual(workflow.artifact_manifest, active)
        self.assertEqual(store.manifest, active)
        self.assertIsNotNone(store.candidate)
        assert store.candidate is not None
        self.assertEqual(store.candidate.stage, "failed")
        self.assertEqual(access.published, [])
        self.assertEqual(access.discarded, ["recipes__green"])

    def test_successful_rebuild_publishes_green_manifest_version(self) -> None:
        config = build_test_config({"graph": {"enable_semantic_graph_schema": False}})
        active = ArtifactManifest(
            stage="ready",
            manifest_version=4,
            index_signature="sig-old",
            index_version="v000004-sig-old",
            collection_name="recipes__blue",
            collection_base_name="recipes",
            collection_slot="blue",
        )
        store = _ManifestStore(active)
        access = _BlueGreenArtifactAccess(build_succeeds=True)
        document_result = DocumentArtifactResult(
            documents=[TextDocument(content="doc")],
            chunks=[TextDocument(content="chunk")],
            manifest=ArtifactManifest(
                stage="documents_ready",
                index_signature="sig-new",
                collection_name="recipes",
                collection_base_name="recipes",
            ),
            cache_hit=False,
        )
        data_module = SimpleNamespace(
            documents=[TextDocument(content="doc")],
            load_graph_data=lambda: None,
            get_statistics=lambda: {"total_chunks": 1},
        )
        workflow = KnowledgeBaseBuildWorkflow(
            config=config,
            neo4j_manager=None,
            data_module=data_module,
            index_module=SimpleNamespace(collection_name="recipes"),
            manifest_store=store,
            runtime_artifact_access=access,
            runtime_stats_access=_RuntimeStats(),
            document_artifact_builder=_DocumentBuilder(document_result),
            semantic_graph_schema_sync=SimpleNamespace(
                sync_from_documents=lambda documents: SemanticGraphSchemaSyncResult(enabled=False)
            ),
        )

        manifest = workflow.rebuild()

        self.assertTrue(manifest.is_ready)
        self.assertEqual(manifest.manifest_version, 5)
        self.assertEqual(manifest.collection_name, "recipes__green")
        self.assertEqual(manifest.collection_base_name, "recipes")
        self.assertEqual(manifest.collection_slot, "green")
        self.assertEqual(manifest.previous_collection_name, "recipes__blue")
        self.assertEqual(manifest.index_version, "v000005-sig-new")
        self.assertEqual(access.published, ["recipes__green"])
        self.assertEqual(access.discarded, [])
        self.assertIsNone(store.candidate)


if __name__ == "__main__":
    unittest.main()

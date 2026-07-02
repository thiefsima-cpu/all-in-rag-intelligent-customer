from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from rag_modules.build_pipeline.document_artifacts import (
    DocumentArtifactBuildService,
    DocumentIndexCache,
)
from rag_modules.build_pipeline.document_artifacts.statistics import DocumentArtifactStatsCollector
from rag_modules.build_pipeline.graph_preparation.statistics import GraphPreparationStats
from rag_modules.text_document import TextDocument


class StubDataModule:
    def __init__(self, *, variant: str = "default") -> None:
        description = "麻辣鲜香的经典川菜。" if variant == "default" else "清淡口味的改良版本。"
        self.recipes = [
            SimpleNamespace(
                node_id="recipe-1",
                labels=["Recipe"],
                name="麻婆豆腐",
                properties={
                    "description": description,
                    "category": "家常菜",
                    "cuisineType": "川菜",
                },
            )
        ]
        self.ingredients = [
            SimpleNamespace(
                node_id="ingredient-1",
                labels=["Ingredient"],
                name="豆腐",
                properties={"category": "豆制品"},
            )
        ]
        self.cooking_steps = [
            SimpleNamespace(
                node_id="step-1",
                labels=["CookingStep"],
                name="焖煮",
                properties={"methods": "焖煮"},
            )
        ]
        self.documents = []
        self.chunks = []
        self.build_calls = 0
        self.chunk_calls = []

    def build_recipe_documents(self):
        self.build_calls += 1
        self.documents = [
            TextDocument(
                content="# 麻婆豆腐\n## 所需食材\n1. 豆腐\n## 制作步骤\n### 第1步\n焖煮",
                metadata={
                    "node_id": "recipe-1",
                    "recipe_name": "麻婆豆腐",
                    "category": "家常菜",
                    "cuisine_type": "川菜",
                    "difficulty": 3,
                    "content_length": 42,
                    "doc_type": "recipe",
                },
            )
        ]
        return self.documents

    def chunk_documents(self, *, chunk_size: int = 500, chunk_overlap: int = 50):
        self.chunk_calls.append((chunk_size, chunk_overlap))
        self.chunks = [
            TextDocument(
                content="## 所需食材\n1. 豆腐",
                metadata={
                    "node_id": "recipe-1",
                    "parent_id": "recipe-1",
                    "chunk_id": "recipe-1_chunk_0",
                    "chunk_index": 0,
                    "total_chunks": 1,
                    "chunk_size": 14,
                    "doc_type": "chunk",
                    "category": "家常菜",
                    "cuisine_type": "川菜",
                },
            )
        ]
        return self.chunks

    def get_statistics(self):
        return {
            "total_recipes": len(self.recipes),
            "total_ingredients": len(self.ingredients),
            "total_cooking_steps": len(self.cooking_steps),
            "total_documents": len(self.documents),
            "total_chunks": len(self.chunks),
        }


class DocumentArtifactCacheTests(unittest.TestCase):
    def _build_config(self, root: Path):
        storage_dir = root / "storage" / "indexes"
        return SimpleNamespace(
            graph=SimpleNamespace(
                chunk_size=128,
                chunk_overlap=16,
            ),
            models=SimpleNamespace(
                embedding_model="qwen3-vl-embedding",
                embedding_dimension=1024,
                embedding_base_url="https://example.test/embeddings",
            ),
            storage=SimpleNamespace(
                enable_index_cache=True,
                index_cache_dir=str(storage_dir),
                artifact_manifest_path=str(storage_dir / "artifact_manifest.json"),
                milvus_collection_name="recipes",
            ),
        )

    def test_cache_save_and_load_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            config = self._build_config(Path(tmp_dir))
            cache = DocumentIndexCache(config)
            writer = StubDataModule()
            writer.build_recipe_documents()
            writer.chunk_documents(chunk_size=128, chunk_overlap=16)

            saved_manifest = cache.save(writer)
            reader = StubDataModule()

            loaded = cache.load(reader)

            self.assertIsNotNone(loaded)
            assert loaded is not None
            self.assertTrue(loaded.cache_hit)
            self.assertEqual(saved_manifest.document_signature, loaded.manifest.document_signature)
            self.assertEqual(len(reader.documents), 1)
            self.assertEqual(len(reader.chunks), 1)
            self.assertEqual(reader.documents[0].metadata["recipe_name"], "麻婆豆腐")
            self.assertEqual(loaded.manifest.build_metadata["document_cache_format"], "json")

    def test_build_service_builds_then_hits_cache(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            config = self._build_config(Path(tmp_dir))
            service = DocumentArtifactBuildService(config)

            builder = StubDataModule()
            first_result = service.build_or_load(builder)

            self.assertFalse(first_result.cache_hit)
            self.assertEqual(builder.build_calls, 1)
            self.assertEqual(builder.chunk_calls, [(128, 16)])
            self.assertEqual(len(first_result.documents), 1)
            self.assertEqual(len(first_result.chunks), 1)

            cached_reader = StubDataModule()
            second_result = service.build_or_load(cached_reader)

            self.assertTrue(second_result.cache_hit)
            self.assertEqual(cached_reader.build_calls, 0)
            self.assertEqual(cached_reader.chunk_calls, [])
            self.assertEqual(second_result.manifest.total_chunks, 1)

    def test_cache_miss_when_graph_signature_changes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            config = self._build_config(Path(tmp_dir))
            cache = DocumentIndexCache(config)
            original = StubDataModule()
            original.build_recipe_documents()
            original.chunk_documents(chunk_size=128, chunk_overlap=16)
            cache.save(original)

            changed = StubDataModule(variant="light")

            loaded = cache.load(changed)

            self.assertIsNone(loaded)
            self.assertEqual(changed.documents, [])
            self.assertEqual(changed.chunks, [])

    def test_cache_miss_when_document_payload_is_tampered(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            config = self._build_config(Path(tmp_dir))
            cache = DocumentIndexCache(config)
            original = StubDataModule()
            original.build_recipe_documents()
            original.chunk_documents(chunk_size=128, chunk_overlap=16)
            cache.save(original)

            documents_path = Path(cache.documents_path)
            payload = json.loads(documents_path.read_text(encoding="utf-8"))
            payload[0]["content"] = "tampered document"
            documents_path.write_text(
                json.dumps(payload, ensure_ascii=False),
                encoding="utf-8",
            )

            self.assertIsNone(cache.load(StubDataModule()))

    def test_stats_collector_accepts_typed_graph_preparation_stats(self) -> None:
        data_module = SimpleNamespace(
            recipes=[],
            ingredients=[],
            cooking_steps=[],
            documents=[],
            chunks=[],
            get_statistics=lambda: GraphPreparationStats(
                total_recipes=2,
                total_ingredients=3,
                total_cooking_steps=4,
                total_documents=5,
                total_chunks=6,
            ),
        )

        stats = DocumentArtifactStatsCollector().collect(data_module)

        self.assertEqual(stats.total_recipes, 2)
        self.assertEqual(stats.total_ingredients, 3)
        self.assertEqual(stats.total_cooking_steps, 4)
        self.assertEqual(stats.total_documents, 5)
        self.assertEqual(stats.total_chunks, 6)


if __name__ == "__main__":
    unittest.main()

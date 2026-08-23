from __future__ import annotations

import unittest

from rag_modules.build_pipeline.graph_preparation import (
    GraphDataPreparationModule,
    create_domain_build_collaborators,
)
from rag_modules.domains import get_domain_pack


class FakeResult(list):
    def single(self):
        return self[0] if self else None


class FakeSession:
    def __init__(self, responses):
        self.responses = responses

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def run(self, query, parameters=None):
        text = " ".join(str(query).split())
        if "RETURN 1 AS test" in text:
            return FakeResult([{"test": 1}])
        if "OPTIONAL MATCH (r)-[:BELONGS_TO_CATEGORY]->(c:Category)" in text:
            return FakeResult(self.responses["recipes"])
        if "MATCH (i:Ingredient)" in text and "REQUIRES" not in text:
            return FakeResult(self.responses["ingredients"])
        if "MATCH (s:CookingStep)" in text and "CONTAINS_STEP" not in text:
            return FakeResult(self.responses["steps"])
        if "MATCH (r:Recipe)-[req:REQUIRES]->(i:Ingredient)" in text:
            return FakeResult(self.responses["recipe_ingredients"])
        if "MATCH (r:Recipe)-[c:CONTAINS_STEP]->(s:CookingStep)" in text:
            return FakeResult(self.responses["recipe_steps"])
        raise AssertionError(f"Unexpected query: {query}")


class FakeDriver:
    def __init__(self, responses):
        self.responses = responses
        self.closed = False

    def session(self, database=None):
        return FakeSession(self.responses)

    def close(self):
        self.closed = True


class GraphDataPreparationModuleTests(unittest.TestCase):
    def _build_driver(self) -> FakeDriver:
        return FakeDriver(
            {
                "recipes": [
                    {
                        "nodeId": "200000001",
                        "labels": ["Recipe"],
                        "name": "麻婆豆腐",
                        "originalProperties": {
                            "description": "麻辣鲜香、很下饭的经典川菜。",
                            "cuisineType": "川菜",
                            "difficulty": 3,
                            "prepTime": "10分钟",
                            "cookTime": "8分钟",
                            "servings": "2人份",
                            "tags": "家常,下饭",
                        },
                        "mainCategory": "家常菜",
                        "allCategories": ["家常菜", "川菜"],
                    }
                ],
                "ingredients": [
                    {
                        "nodeId": "300000001",
                        "labels": ["Ingredient"],
                        "name": "豆腐",
                        "properties": {"category": "豆制品"},
                    },
                    {
                        "nodeId": "300000002",
                        "labels": ["Ingredient"],
                        "name": "豆瓣酱",
                        "properties": {"category": "调味品"},
                    },
                ],
                "steps": [
                    {
                        "nodeId": "400000001",
                        "labels": ["CookingStep"],
                        "name": "煸炒",
                        "properties": {"methods": "煸炒"},
                    }
                ],
                "recipe_ingredients": [
                    {
                        "recipe_id": "200000001",
                        "name": "豆腐",
                        "category": "豆制品",
                        "amount": "1",
                        "unit": "块",
                        "description": "北豆腐更耐煮",
                    },
                    {
                        "recipe_id": "200000001",
                        "name": "豆瓣酱",
                        "category": "调味品",
                        "amount": "2",
                        "unit": "勺",
                        "description": "提供麻辣底味",
                    },
                    {
                        "recipe_id": "200000001",
                        "name": "花椒",
                        "category": "香料",
                        "amount": "1",
                        "unit": "勺",
                        "description": "提升麻香",
                    },
                ],
                "recipe_steps": [
                    {
                        "recipe_id": "200000001",
                        "name": "炒香底料",
                        "description": "将豆瓣酱与花椒炒出红油和香气。",
                        "stepNumber": 1,
                        "methods": "煸炒",
                        "tools": "炒锅",
                        "timeEstimate": "3分钟",
                        "stepOrder": 1,
                    },
                    {
                        "recipe_id": "200000001",
                        "name": "焖煮豆腐",
                        "description": "加入豆腐小火焖煮入味。",
                        "stepNumber": 2,
                        "methods": "焖煮",
                        "tools": "炒锅",
                        "timeEstimate": "5分钟",
                        "stepOrder": 2,
                    },
                ],
            }
        )

    def _build_module(self) -> GraphDataPreparationModule:
        pack = get_domain_pack("recipe")
        loader, document_builder, chunker = create_domain_build_collaborators(pack)
        return GraphDataPreparationModule(
            database="neo4j",
            driver=self._build_driver(),
            loader=loader,
            document_builder=document_builder,
            chunker=chunker,
            domain_name=pack.name,
            domain_version=pack.version,
            data_view=pack.build_data_view,
        )

    def test_load_graph_data_normalizes_recipe_categories(self) -> None:
        module = self._build_module()

        counts = module.load_graph_data()

        self.assertEqual(counts.total_entities, 4)
        self.assertEqual(
            counts.entity_groups,
            {"recipes": 1, "ingredients": 2, "cooking_steps": 1},
        )
        self.assertEqual(module.state.primary_entities[0].properties["category"], "家常菜")
        self.assertEqual(
            module.state.primary_entities[0].properties["all_categories"], ["家常菜", "川菜"]
        )
        self.assertEqual(module.state.related_entity_groups["ingredients"][1].name, "豆瓣酱")

    def test_build_recipe_documents_materializes_semantic_metadata(self) -> None:
        module = self._build_module()
        module.load_graph_data()

        documents = module.build_documents()

        self.assertEqual(len(documents), 1)
        document = documents[0]
        self.assertEqual(document.metadata["node_id"], "200000001")
        self.assertEqual(document.metadata["recipe_name"], "麻婆豆腐")
        self.assertEqual(document.metadata["ingredients_count"], 3)
        self.assertEqual(document.metadata["steps_count"], 2)
        self.assertEqual(document.metadata["doc_type"], "recipe")
        self.assertGreater(document.metadata["content_length"], 0)
        self.assertIn("## 所需食材", document.content)
        self.assertIn("## 制作步骤", document.content)
        self.assertIn("## 语义标签", document.content)
        self.assertTrue(document.metadata["flavor_tags"])
        self.assertIsInstance(document.metadata["semantic_relations"], dict)

    def test_chunking_and_statistics_follow_section_boundaries(self) -> None:
        module = self._build_module()
        module.load_graph_data()
        module.build_documents()

        chunks = module.chunk_documents(chunk_size=80, chunk_overlap=10)
        stats = module.get_statistics()

        self.assertEqual(len(chunks), 6)
        self.assertEqual(chunks[0].metadata["chunk_index"], 0)
        self.assertEqual(chunks[0].metadata["section_title"], "main_title")
        self.assertEqual(chunks[-1].metadata["section_title"], "语义标签")
        self.assertEqual(stats.total_entities, 4)
        self.assertEqual(stats.total_documents, 1)
        self.assertEqual(stats.total_chunks, 6)
        self.assertEqual(stats.domain_metrics["categories"]["家常菜"], 1)
        self.assertEqual(stats.domain_metrics["cuisines"]["川菜"], 1)
        self.assertGreater(stats.avg_chunk_size, 0)
        self.assertEqual(stats.to_dict()["domain_metrics"]["total_recipes"], 1)

    def test_empty_statistics_to_dict_preserves_legacy_sparse_shape(self) -> None:
        module = self._build_module()
        module.load_graph_data()

        stats = module.get_statistics()

        self.assertEqual(
            stats.to_dict(),
            {
                "domain_name": "recipe",
                "total_entities": 4,
                "total_documents": 0,
                "total_chunks": 0,
                "domain_metrics": {
                    "total_recipes": 1,
                    "total_ingredients": 2,
                    "total_cooking_steps": 1,
                    "categories": {},
                    "cuisines": {},
                    "difficulties": {},
                },
                "entity_types": {"Recipe": 1, "Ingredient": 2, "CookingStep": 1},
                "document_types": {},
                "avg_content_length": 0.0,
                "avg_chunk_size": 0.0,
            },
        )

    def test_recipe_document_builder_handles_sparse_invalid_relationship_rows(self) -> None:
        driver = self._build_driver()
        driver.responses["recipes"][0]["originalProperties"].update(
            {
                "difficulty": "invalid",
                "tags": ["quick", "", "quick"],
                "prepTime": "",
                "cookTime": None,
            }
        )
        driver.responses["recipe_ingredients"] = [
            {
                "recipe_id": "200000001",
                "name": "tofu",
                "category": "",
                "amount": None,
                "unit": "",
                "description": "",
            }
        ]
        driver.responses["recipe_steps"] = [
            {
                "recipe_id": "200000001",
                "name": "",
                "description": "simmer",
                "stepNumber": "bad",
                "methods": [],
                "tools": None,
                "timeEstimate": "",
                "stepOrder": "bad",
            }
        ]
        pack = get_domain_pack("recipe")
        loader, document_builder, chunker = create_domain_build_collaborators(pack)
        module = GraphDataPreparationModule(
            database="neo4j",
            driver=driver,
            loader=loader,
            document_builder=document_builder,
            chunker=chunker,
            domain_name=pack.name,
            domain_version=pack.version,
            data_view=pack.build_data_view,
        )
        module.load_graph_data()

        [document] = module.build_documents()

        self.assertEqual(document.metadata["ingredients_count"], 1)
        self.assertEqual(document.metadata["steps_count"], 1)
        self.assertIn("tofu", document.content)
        self.assertIn("simmer", document.content)
        self.assertEqual(document.metadata["difficulty"], "invalid")


if __name__ == "__main__":
    unittest.main()

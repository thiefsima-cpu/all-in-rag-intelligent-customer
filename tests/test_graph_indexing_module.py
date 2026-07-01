from __future__ import annotations

import unittest
from types import SimpleNamespace

from rag_modules.graph_index import GraphIndexingModule
from rag_modules.query_policy import get_query_policy


class GraphIndexingModuleTests(unittest.TestCase):
    def _relation_keyword(self, relation_type: str) -> str:
        keywords = get_query_policy().relations.relation_index_keywords[relation_type]
        self.assertTrue(keywords)
        return keywords[0]

    def _semantic_relation_key(self, relation_type: str) -> str:
        specs = get_query_policy().graph.reasoning.semantic_relation_key_specs
        self.assertIn(relation_type, specs)
        return relation_type

    def _build_module(self) -> GraphIndexingModule:
        config = SimpleNamespace(enable_llm_relation_keys=False)
        module = GraphIndexingModule(config, llm_client=SimpleNamespace())
        recipe = SimpleNamespace(
            node_id="r1",
            name="mapo tofu",
            properties={
                "category": "home cooking",
                "cuisineType": "sichuan",
                "flavor_tags": ["spicy"],
                "technique_tags": ["stir fry"],
                "health_tags": ["protein"],
                "semantic_relations": {
                    "HAS_FLAVOR": ["spicy"],
                    "CONTRIBUTES_TO": [
                        {"effect": "umami", "causes": ["doubanjiang", "peppercorn"]}
                    ],
                },
            },
        )
        ingredient = SimpleNamespace(
            node_id="i1",
            name="tofu",
            properties={"category": "soy product", "nutrition": "protein"},
        )
        step = SimpleNamespace(
            node_id="s1",
            name="step 1",
            properties={"description": "stir fry aromatics", "technique": "stir fry", "time": "3m"},
        )
        module.create_entity_key_values([recipe], [ingredient], [step])
        module.create_relation_key_values(
            [
                ("r1", "REQUIRES", "i1"),
                ("r1", "REQUIRES", "i1"),
                ("r1", "CONTAINS_STEP", "s1"),
            ]
        )
        return module

    def test_entity_index_builds_lookup_keys(self) -> None:
        module = self._build_module()

        results = module.get_entities_by_key("spicy")

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].entity_name, "mapo tofu")
        self.assertIn("sichuan", results[0].index_keys)

    def test_relation_index_builds_graph_and_semantic_relations(self) -> None:
        module = self._build_module()

        graph_relations = module.get_relations_by_key(self._relation_keyword("REQUIRES"))
        semantic_relations = module.get_relations_by_key(
            self._semantic_relation_key("CONTRIBUTES_TO")
        )

        self.assertTrue(any(item.relation_type == "REQUIRES" for item in graph_relations))
        self.assertTrue(
            any(item.metadata.get("created_from_semantic_schema") for item in semantic_relations)
        )
        self.assertTrue(
            any(
                item.metadata.get("created_from_semantic_schema")
                for item in module.get_relations_by_key("doubanjiang")
            )
        )

    def test_snapshot_round_trip_and_deduplication(self) -> None:
        module = self._build_module()
        module.deduplicate_entities_and_relations()
        payload = module.to_cache_dict()

        restored = GraphIndexingModule(
            SimpleNamespace(enable_llm_relation_keys=False), llm_client=None
        )
        loaded = restored.from_cache_dict(payload)

        self.assertTrue(loaded)
        self.assertEqual(restored.get_statistics()["total_entities"], 3)
        self.assertEqual(restored.get_statistics()["total_relations"], 4)
        self.assertEqual(
            len(
                [
                    item
                    for item in restored.get_relations_by_key(self._relation_keyword("REQUIRES"))
                    if item.relation_type == "REQUIRES"
                ]
            ),
            1,
        )
        self.assertTrue(restored.get_relations_by_key(self._relation_keyword("CONTAINS_STEP")))


if __name__ == "__main__":
    unittest.main()

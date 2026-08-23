from __future__ import annotations

import unittest
from types import SimpleNamespace

from rag_modules.graph_index import GraphIndexingModule
from rag_modules.query_policy import get_query_policy
from rag_modules.query_policy.selector import resolve_query_policy_bundle


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
        module.create_entity_key_values([recipe, ingredient, step])
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

    def test_entity_index_materializes_full_and_sparse_node_properties(self) -> None:
        module = GraphIndexingModule(
            SimpleNamespace(enable_llm_relation_keys=False), llm_client=None
        )
        recipe = SimpleNamespace(
            node_id="r-full",
            name="full recipe",
            properties={
                "description": "description",
                "category": "main",
                "cuisineType": "sichuan",
                "difficulty": "easy",
                "cookingTime": "20m",
                "flavor_tags": ["spicy"],
                "technique_tags": ["fry"],
                "diet_tags": ["vegan"],
                "health_tags": ["protein"],
                "cuisine_style_tags": ["home"],
                "ingredient_category_tags": ["soy"],
                "time_profile_tags": ["quick"],
                "difficulty_level_tags": ["beginner"],
            },
        )
        sparse_recipe = SimpleNamespace(node_id="r-sparse", name="", properties=None)
        ingredient = SimpleNamespace(
            node_id="i-full",
            name="tofu",
            properties={"category": "soy", "nutrition": "protein", "storage": "cold"},
        )
        sparse_ingredient = SimpleNamespace(node_id="i-sparse", name="", properties={})
        step = SimpleNamespace(
            node_id="s-full",
            properties={
                "description": "stir ingredients",
                "order": 1,
                "technique": "stir fry",
                "time": "3m",
            },
        )
        sparse_step = SimpleNamespace(node_id="s-sparse", properties={})

        module.create_entity_key_values(
            [recipe, sparse_recipe, ingredient, sparse_ingredient, step, sparse_step]
        )

        full_recipe = module.entity_kv_store["r-full"]
        self.assertIn("description", full_recipe.value_content)
        self.assertIn("beginner", full_recipe.value_content)
        self.assertIn("vegan", full_recipe.index_keys)
        self.assertTrue(module.entity_kv_store["r-sparse"].entity_name)
        self.assertIn("cold", module.entity_kv_store["i-full"].value_content)
        self.assertTrue(module.entity_kv_store["i-sparse"].entity_name)
        self.assertIn("stir fry", module.entity_kv_store["s-full"].value_content)

    def test_domain_entity_index_uses_labels_and_customer_properties(self) -> None:
        module = GraphIndexingModule(
            SimpleNamespace(enable_llm_relation_keys=False), llm_client=None
        )
        order = SimpleNamespace(
            node_id="CS-1001",
            name="订单 CS-1001",
            labels=["Order"],
            properties={
                "domain": "customer_service",
                "status": "已发货",
                "updated_at": "2026-07-17",
            },
        )

        module.create_domain_entity_key_values([order])

        indexed = module.entity_kv_store["CS-1001"]
        self.assertEqual(indexed.entity_type, "Order")
        self.assertEqual(indexed.metadata["domain"], "customer_service")
        self.assertIn("已发货", indexed.index_keys)
        self.assertIn("updated_at: 2026-07-17", indexed.value_content)

    def test_customer_relation_index_uses_selected_policy_bundle(self) -> None:
        config = SimpleNamespace(
            enable_llm_relation_keys=False,
            query_understanding=SimpleNamespace(
                policy=SimpleNamespace(
                    bundle="customer-service-v1",
                    bundle_path="",
                )
            ),
        )
        module = GraphIndexingModule(config, llm_client=None)
        module.create_domain_entity_key_values(
            [
                SimpleNamespace(
                    node_id="POL-REFUND-2026-07",
                    name="2026.07",
                    labels=["RefundPolicy"],
                    properties={"domain": "customer_service"},
                ),
                SimpleNamespace(
                    node_id="POL-REFUND-2026-06",
                    name="2026.06",
                    labels=["RefundPolicy"],
                    properties={"domain": "customer_service"},
                ),
            ]
        )

        module.create_relation_key_values(
            [("POL-REFUND-2026-07", "SUPERSEDES", "POL-REFUND-2026-06")]
        )

        policy = resolve_query_policy_bundle(config)
        keyword = policy.relations.relation_index_keywords["SUPERSEDES"][0]
        relations = module.get_relations_by_key(keyword)
        self.assertTrue(any(item.relation_type == "SUPERSEDES" for item in relations))
        self.assertEqual(relations[0].metadata["domain"], "customer_service")


if __name__ == "__main__":
    unittest.main()

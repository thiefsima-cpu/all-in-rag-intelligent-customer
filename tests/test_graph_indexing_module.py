from __future__ import annotations

import unittest
from types import SimpleNamespace

from rag_modules.graph_index import GraphIndexingModule


class GraphIndexingModuleTests(unittest.TestCase):
    def _build_module(self) -> GraphIndexingModule:
        config = SimpleNamespace(enable_llm_relation_keys=False)
        module = GraphIndexingModule(config, llm_client=SimpleNamespace())
        recipe = SimpleNamespace(
            node_id="r1",
            name="麻婆豆腐",
            properties={
                "category": "家常菜",
                "cuisineType": "川菜",
                "flavor_tags": ["麻辣"],
                "technique_tags": ["滑油"],
                "health_tags": ["下饭"],
                "semantic_relations": {
                    "HAS_FLAVOR": ["麻辣"],
                    "CONTRIBUTES_TO": [{"effect": "鲜香", "causes": ["豆瓣酱", "花椒"]}],
                },
            },
        )
        ingredient = SimpleNamespace(
            node_id="i1",
            name="豆腐",
            properties={"category": "豆制品", "nutrition": "高蛋白"},
        )
        step = SimpleNamespace(
            node_id="s1",
            name="步骤1",
            properties={"description": "下锅翻炒", "technique": "翻炒", "time": "3分钟"},
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

        results = module.get_entities_by_key("麻辣")

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].entity_name, "麻婆豆腐")
        self.assertIn("川菜", results[0].index_keys)

    def test_relation_index_builds_graph_and_semantic_relations(self) -> None:
        module = self._build_module()

        graph_relations = module.get_relations_by_key("食材搭配")
        semantic_relations = module.get_relations_by_key("麻辣")

        self.assertTrue(any(item.relation_type == "REQUIRES" for item in graph_relations))
        self.assertTrue(
            any(item.metadata.get("created_from_semantic_schema") for item in semantic_relations)
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
                    for item in restored.get_relations_by_key("食材搭配")
                    if item.relation_type == "REQUIRES"
                ]
            ),
            1,
        )
        self.assertTrue(restored.get_relations_by_key("制作步骤"))


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import unittest

from rag_modules.answer_evidence_builder import AnswerEvidenceBuilder
from rag_modules.contracts import EvidenceDocument


class AnswerEvidenceBuilderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.builder = AnswerEvidenceBuilder(max_content_chars=120)

    def test_builder_prefers_evidence_documents_as_primary_input(self) -> None:
        docs = [
            EvidenceDocument(
                content="水煮肉片通过豆瓣酱、花椒和辣椒形成麻辣鲜香的风味。",
                recipe_id="recipe-1",
                recipe_name="水煮肉片",
                source="graph_rag",
                score=0.95,
                matched_terms=["麻辣", "花椒"],
                evidence_units=[
                    {
                        "claim": "豆瓣酱、花椒和辣椒共同贡献麻辣鲜香。",
                        "evidence_type": "graph_relation",
                        "relation_type": "CONTRIBUTES_TO",
                        "entities": ["豆瓣酱", "花椒", "辣椒", "麻辣鲜香"],
                        "is_graph_evidence": True,
                    }
                ],
            ),
            EvidenceDocument(
                content="肉片上浆能帮助口感更滑嫩。",
                recipe_id="recipe-1",
                recipe_name="水煮肉片",
                source="graph_rag",
                score=0.88,
                matched_terms=["上浆", "滑嫩"],
            ),
        ]

        package = self.builder.build("为什么水煮肉片会麻辣鲜香？", docs)

        self.assertEqual(len(package.items), 1)
        self.assertEqual(package.items[0].recipe_name, "水煮肉片")
        self.assertEqual(package.items[0].citation, "菜谱证据 1")
        self.assertIn("麻辣", package.items[0].matched_terms)

    def test_document_wrapper_stays_compatible(self) -> None:
        evidence = EvidenceDocument(
            content="宫保鸡丁是一道经典川菜。",
            recipe_id="recipe-2",
            recipe_name="宫保鸡丁",
            source="hybrid",
            score=0.9,
        )

        package = self.builder.build_from_documents("宫保鸡丁怎么做？", [evidence.to_langchain()])

        self.assertEqual(len(package.items), 1)
        self.assertEqual(package.items[0].recipe_name, "宫保鸡丁")


if __name__ == "__main__":
    unittest.main()

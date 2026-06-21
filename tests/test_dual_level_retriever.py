from __future__ import annotations

import unittest
from types import SimpleNamespace

from rag_modules.retrieval.contracts import EvidenceDocument, RetrievalRequest
from rag_modules.retrieval.dual_level_evidence_service import DualLevelEvidenceService
from rag_modules.retrieval.dual_level_retriever import DualLevelRetriever


class _FakeKeywordExtractor:
    def extract(self, query):
        return [f"entity::{query}"], [f"topic::{query}"]

    @staticmethod
    def dedupe_terms(terms):
        return list(dict.fromkeys(terms))


class _FakeGraphKVRetriever:
    def entity_search(self, keywords, top_k=5):
        del top_k
        if not keywords:
            return []
        return [
            EvidenceDocument(
                content="entity-content",
                node_id="n1",
                recipe_name="RecipeA",
                score=0.82,
                metadata={"relevance_score": 0.82, "entity_type": "Recipe"},
            )
        ]

    def topic_search(self, keywords, top_k=5):
        del top_k
        if not keywords:
            return []
        return [
            EvidenceDocument(
                content="topic-content",
                node_id="rel-source",
                recipe_name="",
                score=0.73,
                metadata={
                    "relevance_score": 0.73,
                    "source_entity": "rel-source",
                    "source_name": "RecipeB",
                    "target_name": "LightFlavor",
                    "matched_keyword": keywords[0],
                    "relation_type": "HAS_FLAVOR",
                },
            )
        ]


class _FakeFallbackRetriever:
    def entity_search(self, keywords, limit):
        del keywords
        return [
            EvidenceDocument(
                content=f"fallback-entity-{limit}",
                node_id="n2",
                recipe_name="RecipeFallback",
                score=0.6,
                search_method="neo4j_fallback",
            )
        ]

    def topic_search(self, keywords, limit):
        del keywords
        return [
            EvidenceDocument(
                content=f"fallback-topic-{limit}",
                node_id="n3",
                recipe_name="RecipeTopicFallback",
                score=0.5,
                search_method="neo4j_fallback",
            )
        ]

    def node_neighbors(self, node_id, max_neighbors=3):
        del max_neighbors
        if node_id == "n1":
            return ["NeighborA", "NeighborB"]
        return []


class DualLevelRetrieverTests(unittest.TestCase):
    def setUp(self) -> None:
        graph_indexing = SimpleNamespace(
            entity_kv_store={
                "rel-source": SimpleNamespace(
                    entity_name="RecipeB",
                    entity_type="Recipe",
                    value_content="RecipeB first line\nmore",
                )
            },
            get_entities_by_key=lambda keyword: (
                [
                    SimpleNamespace(
                        entity_name="RecipeCategory",
                        entity_type="Recipe",
                        value_content="category-hit",
                        metadata={"node_id": "n4"},
                    )
                ]
                if keyword == "light"
                else []
            ),
        )
        self.retriever = DualLevelRetriever(
            driver=None,
            database="neo4j",
            graph_indexing=graph_indexing,
            graph_kv_retriever=_FakeGraphKVRetriever(),
            keyword_extractor=_FakeKeywordExtractor(),
            evidence_service=DualLevelEvidenceService(graph_indexing=graph_indexing),
            fallback_retriever=_FakeFallbackRetriever(),
        )

    def test_entity_level_retrieval_enriches_neighbors_and_fallback(self) -> None:
        results = self.retriever.entity_level_retrieval(["tofu"], top_k=2)

        self.assertEqual(len(results), 2)
        self.assertIn("相关信息: NeighborA, NeighborB", results[0].content)
        self.assertEqual(results[0].retrieval_level, "entity")
        self.assertEqual(results[1].search_method, "neo4j_fallback")

    def test_topic_level_retrieval_composes_recipe_context_and_category_hits(self) -> None:
        results = self.retriever.topic_level_retrieval(["light"], top_k=3)

        self.assertEqual([doc.recipe_name for doc in results[:2]], ["RecipeCategory", "RecipeB"])
        self.assertIn("主题: light", results[1].content)
        self.assertIn("菜谱详情: RecipeB first line", results[1].content)

    def test_search_resolves_keywords_from_request(self) -> None:
        request = RetrievalRequest.from_inputs(query="query", top_k=2)
        results = self.retriever.search(request)

        self.assertEqual(len(results), 2)
        self.assertEqual(results[0].recipe_name, "RecipeA")


if __name__ == "__main__":
    unittest.main()

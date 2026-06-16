from __future__ import annotations

import unittest

from langchain_core.documents import Document

from rag_modules.retrieval.contracts import EvidenceDocument
from rag_modules.runtime.retrieval_models import RetrievalOutcome
from rag_modules.runtime.workflow_models import AnswerContext


class RetrievalRuntimeModelTests(unittest.TestCase):
    def test_retrieval_outcome_uses_evidence_as_canonical_payload(self) -> None:
        evidence = EvidenceDocument(
            content="宫保鸡丁是一道经典川菜。",
            recipe_name="宫保鸡丁",
            source="hybrid",
            score=0.91,
        )
        outcome = RetrievalOutcome(
            query="宫保鸡丁怎么做？",
            strategy="hybrid_traditional",
            evidence_documents=[evidence],
        )

        self.assertEqual(outcome.doc_count, 1)
        self.assertEqual(outcome.evidence_documents[0].recipe_name, "宫保鸡丁")
        self.assertEqual(outcome.documents[0].metadata["recipe_name"], "宫保鸡丁")

    def test_retrieval_outcome_accepts_legacy_documents_input(self) -> None:
        legacy_doc = Document(
            page_content="水煮肉片通常带有麻辣鲜香的风味。",
            metadata={
                "recipe_name": "水煮肉片",
                "source": "graph_rag",
                "score": 0.88,
            },
        )
        outcome = RetrievalOutcome(documents_input=[legacy_doc])

        self.assertEqual(len(outcome.evidence_documents), 1)
        self.assertEqual(outcome.evidence_documents[0].recipe_name, "水煮肉片")

    def test_answer_context_round_trips_from_dict_payload(self) -> None:
        context = AnswerContext(
            question="为什么水煮肉片会麻辣鲜香？",
            retrieval={
                "query": "为什么水煮肉片会麻辣鲜香？",
                "strategy": "graph_rag",
                "evidence_documents": [
                    {
                        "content": "豆瓣酱、花椒和辣椒共同贡献麻辣鲜香。",
                        "recipe_name": "水煮肉片",
                        "source": "graph_rag",
                        "score": 0.95,
                    }
                ],
            },
        )

        self.assertEqual(len(context.evidence_documents), 1)
        self.assertEqual(context.evidence_documents[0].recipe_name, "水煮肉片")
        self.assertEqual(context.documents[0].metadata["recipe_name"], "水煮肉片")


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import unittest

from rag_modules.contracts import EvidenceDocument
from rag_modules.runtime import RouteSnapshot, RouteStageSnapshot
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
        self.assertFalse(hasattr(outcome, "documents"))

    def test_retrieval_outcome_exposes_route_degradation_summary(self) -> None:
        route_trace = RouteSnapshot(
            query="recommend tofu dishes",
            strategy="hybrid_traditional",
            stages={
                "hybrid": RouteStageSnapshot(
                    doc_count=1,
                    details={
                        "retrieval_degraded": True,
                        "degraded_sources": ["vector"],
                        "circuit_breaker_triggered": True,
                        "answer_impacted": False,
                        "degraded_candidates": [
                            {
                                "source": "vector",
                                "error": {
                                    "code": "CANDIDATE_SOURCE_CIRCUIT_OPEN",
                                    "detail": "candidate_source_circuit_open",
                                },
                            }
                        ],
                    },
                )
            },
            final_doc_count=1,
        )
        outcome = RetrievalOutcome(
            query="recommend tofu dishes",
            strategy="hybrid_traditional",
            evidence_documents=[EvidenceDocument(content="doc", recipe_name="Mapo Tofu")],
            route_trace=route_trace,
        )

        self.assertTrue(outcome.degradation_summary["retrieval_degraded"])
        self.assertEqual(outcome.degradation_summary["degraded_sources"], ["vector"])
        self.assertTrue(outcome.degradation_summary["circuit_breaker_triggered"])
        self.assertFalse(outcome.degradation_summary["answer_impacted"])
        self.assertEqual(
            outcome.to_dict()["degradation_summary"]["degraded_candidates"][0]["error"]["detail"],
            "candidate_source_circuit_open",
        )

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
        self.assertFalse(hasattr(context, "documents"))


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import time
import unittest

import pytest

from rag_modules.contracts import (
    EvidenceDocument,
    RequestBudgetExceeded,
    RequestCancelled,
    RequestControl,
    RetrievalRequest,
)
from rag_modules.contracts.runtime import (
    RouteSnapshot,
    RouteStageSnapshot,
)
from rag_modules.contracts.runtime.retrieval import RetrievalOutcome
from rag_modules.contracts.runtime.workflows import AnswerContext


def test_request_control_child_uses_tighter_deadline_and_shared_cancel() -> None:
    parent = RequestControl.for_timeout(10.0, scope="answer")
    child = parent.child(0.25, scope="combined.graph")

    assert child.scope == "combined.graph"
    assert child.deadline <= time.perf_counter() + 0.30
    assert child.deadline <= parent.deadline

    child.cancel("combined_branch_timeout")

    assert parent.cancelled
    assert child.cancelled
    assert parent.reason == "combined_branch_timeout"
    assert child.reason == "combined_branch_timeout"


def test_request_control_raises_cancelled_and_budget_exceeded() -> None:
    cancelled = RequestControl.for_timeout(5.0, scope="answer")
    cancelled.cancel("client_disconnect")

    with pytest.raises(RequestCancelled, match="client_disconnect"):
        cancelled.raise_if_cancelled()

    exhausted = RequestControl(deadline=time.perf_counter() - 0.01, scope="answer")

    with pytest.raises(RequestBudgetExceeded, match="answer"):
        exhausted.raise_if_cancelled()


def test_retrieval_request_serializes_safe_control_details_only() -> None:
    control = RequestControl.for_timeout(5.0, scope="route")
    request = RetrievalRequest.from_inputs(query="tofu", top_k=2, control=control)

    payload = request.to_dict()

    assert payload["control"]["scope"] == "route"
    assert payload["control"]["cancelled"] is False
    assert "cancel_event" not in str(payload)


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

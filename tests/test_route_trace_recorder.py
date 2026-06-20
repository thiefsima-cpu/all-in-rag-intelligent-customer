from __future__ import annotations

import unittest

from rag_modules.query_understanding import QueryPlan, QuerySemanticProfile
from rag_modules.retrieval.contracts import EvidenceDocument, RetrievalRequest
from rag_modules.routing import RouteTraceRecorder
from rag_modules.routing.execution_strategies import (
    RouteExecutionOutcome,
    RouteExecutionStageResult,
)


class RouteTraceRecorderTests(unittest.TestCase):
    def test_record_plan_and_stage_snapshot(self) -> None:
        recorder = RouteTraceRecorder(query="why is fish-fragrant pork layered", requested_top_k=3)
        plan = QueryPlan(query="why is fish-fragrant pork layered")
        plan.strategy = "graph_rag"
        plan.used_cache = True
        plan.semantic_profile = QuerySemanticProfile.from_dict(
            {
                **plan.semantic_profile.to_dict(),
                "relation_hits": ["relation", "influence"],
            }
        )

        recorder.record_plan(plan, start_time=0.0)
        recorder.set_strategy("graph_rag")
        recorder.set_retrieval_request(
            RetrievalRequest.from_inputs(query=plan.query, top_k=3, strategy="graph_rag")
        )
        recorder.add_stage(
            "graph_rag",
            start_time=0.0,
            documents=[
                EvidenceDocument(
                    content="graph evidence",
                    recipe_name="Fish-Fragrant Pork",
                    source="graph_rag",
                    search_method="graph_rag",
                )
            ],
            details={"path_count": 2},
        )
        snapshot = recorder.finalize(total_start_time=0.0, final_doc_count=1)

        self.assertEqual(snapshot.strategy, "graph_rag")
        self.assertIn("plan", snapshot.stages)
        self.assertEqual(snapshot.stages["graph_rag"].doc_count, 1)
        self.assertEqual(snapshot.stages["graph_rag"].details["path_count"], 2)
        self.assertEqual(snapshot.diagnostics.graph_doc_count, 1)
        self.assertEqual(snapshot.final_doc_count, 1)

    def test_record_execution_outcome_applies_fallbacks_and_latency_snapshots(self) -> None:
        recorder = RouteTraceRecorder(query="recommend tofu dishes", requested_top_k=2)
        document = EvidenceDocument(content="doc", recipe_name="Mapo Tofu", source="hybrid")
        outcome = RouteExecutionOutcome(
            documents=[document],
            fallbacks=["graph_empty_to_hybrid"],
            stages=[
                RouteExecutionStageResult(
                    name="hybrid_fallback",
                    documents=[document],
                    latency_ms=15.5,
                    details={"candidate_k": 3},
                )
            ],
        )

        recorder.record_execution_outcome(outcome)
        clone = recorder.clone_snapshot()

        self.assertEqual(clone.fallbacks, ["graph_empty_to_hybrid"])
        self.assertIn("hybrid_fallback", clone.stages)
        self.assertEqual(clone.stages["hybrid_fallback"].latency_ms, 15.5)
        self.assertEqual(clone.stages["hybrid_fallback"].details["candidate_k"], 3)

    def test_route_diagnostics_summarize_retrieval_degradation(self) -> None:
        recorder = RouteTraceRecorder(query="recommend tofu dishes", requested_top_k=2)
        document = EvidenceDocument(content="doc", recipe_name="Mapo Tofu", source="hybrid")
        outcome = RouteExecutionOutcome(
            documents=[document],
            stages=[
                RouteExecutionStageResult(
                    name="hybrid",
                    documents=[document],
                    latency_ms=10.0,
                    details={
                        "retrieval_degraded": True,
                        "degraded_sources": ["vector"],
                        "circuit_breaker_triggered": True,
                        "answer_impacted": False,
                        "degraded_candidates": [
                            {
                                "source": "vector",
                                "rank_name": "vector",
                                "reason": "circuit_open",
                                "error_type": "CircuitOpenError",
                                "message": "Circuit breaker open",
                                "circuit_state": "open",
                                "failure_count": 2,
                            }
                        ],
                    },
                )
            ],
        )

        recorder.record_execution_outcome(outcome)
        snapshot = recorder.finalize(total_start_time=0.0, final_doc_count=1)

        self.assertTrue(snapshot.diagnostics.retrieval_degraded)
        self.assertEqual(snapshot.diagnostics.degraded_sources, ["vector"])
        self.assertTrue(snapshot.diagnostics.circuit_breaker_triggered)
        self.assertFalse(snapshot.diagnostics.answer_impacted)
        self.assertEqual(snapshot.diagnostics.degraded_candidates[0]["reason"], "circuit_open")


if __name__ == "__main__":
    unittest.main()

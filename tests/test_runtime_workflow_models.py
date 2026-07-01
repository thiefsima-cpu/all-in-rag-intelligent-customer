from __future__ import annotations

import unittest
from types import SimpleNamespace

from rag_modules.answer_evidence_builder import AnswerEvidenceItem, AnswerEvidencePackage
from rag_modules.contracts import EvidenceDocument, QueryPlan
from rag_modules.observability.tracing import QueryTracer
from rag_modules.runtime import (
    AnswerContext,
    QueryUnderstandingSnapshot,
    RetrievalOutcome,
    RouteResolution,
    SearchStrategy,
)


class RuntimeWorkflowModelTests(unittest.TestCase):
    def test_route_resolution_builds_canonical_answer_context(self) -> None:
        understanding = QueryUnderstandingSnapshot.from_plan(
            QueryPlan(
                query="why does dish A work",
                strategy="graph_rag",
                complexity=0.84,
                relationship_intensity=0.78,
                reasoning_required=True,
            )
        )
        retrieval = RetrievalOutcome(
            query="why does dish A work",
            strategy="graph_rag",
            evidence_documents=[
                EvidenceDocument(
                    content="dish A balances ingredient X and Y",
                    recipe_name="dish A",
                    source="graph_rag",
                    score=0.93,
                )
            ],
        )

        resolution = RouteResolution(understanding=understanding, retrieval=retrieval)
        context = AnswerContext.from_route_resolution(resolution)

        self.assertEqual(context.question, "why does dish A work")
        self.assertEqual(context.analysis.strategy_name, "graph_rag")
        self.assertIs(context.understanding.query_plan.strategy, SearchStrategy.GRAPH_RAG)
        self.assertEqual(len(context.evidence_documents), 1)

    def test_answer_context_round_trips_with_evidence_package_payload(self) -> None:
        package = AnswerEvidencePackage(
            question="how to make dish A",
            items=[
                AnswerEvidenceItem(
                    citation="Recipe Evidence 1",
                    recipe_id="recipe-1",
                    recipe_name="dish A",
                    confidence=0.91,
                    evidence_units=[{"claim": "dish A uses ingredient X"}],
                    content="dish A uses ingredient X and Y",
                )
            ],
        )

        context = AnswerContext(question="how to make dish A").with_evidence_package(package)
        round_trip = AnswerContext(**context.to_dict())

        self.assertTrue(round_trip.has_evidence_package)
        rebuilt_package = AnswerEvidencePackage.from_dict(round_trip.evidence_package)
        self.assertEqual(rebuilt_package.question, "how to make dish A")
        self.assertEqual(rebuilt_package.items[0].citation, "Recipe Evidence 1")

    def test_query_tracer_reads_query_plan_from_answer_context_contract(self) -> None:
        understanding = QueryUnderstandingSnapshot.from_plan(
            QueryPlan(
                query="why does dish A work",
                strategy="graph_rag",
                complexity=0.84,
                relationship_intensity=0.78,
                reasoning_required=True,
            )
        )
        retrieval = RetrievalOutcome(
            query="why does dish A work",
            strategy="graph_rag",
            evidence_documents=[
                EvidenceDocument(
                    content="dish A balances ingredient X and Y",
                    recipe_name="dish A",
                    source="graph_rag",
                    score=0.93,
                )
            ],
        )
        context = AnswerContext.from_route_resolution(
            RouteResolution(understanding=understanding, retrieval=retrieval)
        )
        tracer = QueryTracer(
            SimpleNamespace(
                models=SimpleNamespace(
                    llm_model="qwen3.7-plus",
                    embedding_model="qwen3-vl-embedding",
                    rerank_model="qwen3-vl-rerank",
                ),
                observability=SimpleNamespace(
                    enable_query_tracing=False,
                    query_trace_path="trace.jsonl",
                ),
            )
        )

        event = tracer.record(
            query=context.question,
            analysis=context.analysis,
            documents=context,
            latency_ms=12.0,
            answer="grounded answer",
        )

        self.assertEqual(event.plan["strategy"], "graph_rag")
        self.assertEqual(event.strategy, "graph_rag")


if __name__ == "__main__":
    unittest.main()

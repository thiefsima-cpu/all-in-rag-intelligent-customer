from __future__ import annotations

import unittest
from types import SimpleNamespace

from rag_modules.configuration.testing import build_test_config
from rag_modules.query_constraints import QueryConstraints
from rag_modules.retrieval.candidate_generator import (
    CandidateSet,
    CandidateSourceDegradation,
    CandidateSourceResult,
)
from rag_modules.retrieval.candidate_sources import CandidateSourceSpec
from rag_modules.retrieval.contracts import EvidenceDocument
from rag_modules.retrieval.hybrid_search_service import HybridSearchService


class _FakeFusionRanker:
    def __init__(self) -> None:
        self.rrf_k = 60
        self.calls = []

    def rrf_merge(self, *, ranked_lists, top_k):
        self.calls.append({"ranked_lists": ranked_lists, "top_k": top_k})
        merged = []
        for _, documents in ranked_lists:
            merged.extend(documents)
        return merged[:top_k]


class _FakeCandidatesProfile:
    def hybrid_candidate_k(self, top_k: int, *, constrained: bool) -> int:
        return top_k + (2 if constrained else 1)


class _FakeRetrievalProfile:
    def __init__(self) -> None:
        self.candidates = _FakeCandidatesProfile()


class _FakeRuntime:
    def __init__(self) -> None:
        self.attach_calls = []

    def attach_parent_evidence_documents(self, docs, *, top_n=None):
        self.attach_calls.append({"docs": list(docs), "top_n": top_n})
        return list(docs)


class _StubCandidateGenerator:
    def __init__(self, *, degrade_vector: bool = False) -> None:
        self.requests = []
        self.degrade_vector = degrade_vector

    def generate(self, request):
        self.requests.append(request)
        vector_spec = CandidateSourceSpec(
            name="vector",
            rank_name="vector",
            search_method="vector",
            search_type="vector_enhanced",
            rank_order=2,
        )
        degraded = []
        if self.degrade_vector:
            degraded.append(
                CandidateSourceDegradation(
                    spec=vector_spec,
                    reason="circuit_open",
                    error_type="CircuitOpenError",
                    message="Circuit breaker open",
                    circuit_state="open",
                    failure_count=2,
                )
            )
        return CandidateSet(
            source_results=[
                CandidateSourceResult(
                    spec=CandidateSourceSpec(
                        name="constraints",
                        rank_name="constraints",
                        search_method="constraints",
                        search_type="constraint_recipe",
                        rank_order=0,
                    ),
                    documents=[EvidenceDocument(content="c", recipe_name="C")],
                ),
                CandidateSourceResult(
                    spec=vector_spec,
                    documents=[EvidenceDocument(content="v", recipe_name="V")],
                ),
            ],
            degraded=degraded,
        )


class _StubCandidateSourceFactory:
    def __init__(self) -> None:
        self.calls = []

    def build(self, *, runtime, constraint_retriever):
        self.calls.append(
            {
                "runtime": runtime,
                "constraint_retriever": constraint_retriever,
            }
        )
        return ()


class HybridSearchServiceTests(unittest.TestCase):
    def test_hybrid_evidence_search_uses_generator_and_parent_enrichment(self) -> None:
        config = build_test_config({"retrieval": {"enable_parent_doc_retrieval": True}})
        runtime = _FakeRuntime()
        generator = _StubCandidateGenerator()
        fusion_ranker = _FakeFusionRanker()
        service = HybridSearchService(
            config=config,
            retrieval_profile=_FakeRetrievalProfile(),
            runtime=runtime,
            fusion_ranker=fusion_ranker,
            constraint_retriever=SimpleNamespace(),
            candidate_generator=generator,
        )

        outcome = service.hybrid_evidence_search(
            "recommend tofu dishes",
            top_k=2,
            constraints=QueryConstraints(max_cook_minutes=30),
        )

        self.assertEqual([doc.recipe_name for doc in outcome.documents], ["C", "V"])
        self.assertEqual(generator.requests[0].candidate_k, 4)
        self.assertEqual(runtime.attach_calls[0]["top_n"], 2)
        self.assertEqual(
            [name for name, _ in fusion_ranker.calls[0]["ranked_lists"]],
            ["constraints", "vector"],
        )
        self.assertFalse(outcome.retrieval_degraded)

    def test_hybrid_evidence_search_returns_degradation_observability(self) -> None:
        config = build_test_config({"retrieval": {"enable_parent_doc_retrieval": False}})
        service = HybridSearchService(
            config=config,
            retrieval_profile=_FakeRetrievalProfile(),
            runtime=_FakeRuntime(),
            fusion_ranker=_FakeFusionRanker(),
            constraint_retriever=SimpleNamespace(),
            candidate_generator=_StubCandidateGenerator(degrade_vector=True),
        )

        outcome = service.hybrid_evidence_search("recommend tofu dishes", top_k=2)

        self.assertEqual([doc.recipe_name for doc in outcome.documents], ["C", "V"])
        self.assertTrue(outcome.retrieval_degraded)
        self.assertEqual(outcome.degraded_sources, ["vector"])
        self.assertTrue(outcome.circuit_breaker_triggered)
        self.assertFalse(outcome.answer_impacted)
        self.assertEqual(outcome.degraded_candidates[0]["reason"], "circuit_open")
        self.assertEqual(outcome.to_stage_details()["candidate_counts"]["vector"], 1)

    def test_candidate_source_factory_is_used_when_generator_not_injected(self) -> None:
        config = build_test_config()
        runtime = _FakeRuntime()
        source_factory = _StubCandidateSourceFactory()
        service = HybridSearchService(
            config=config,
            retrieval_profile=_FakeRetrievalProfile(),
            runtime=runtime,
            fusion_ranker=_FakeFusionRanker(),
            constraint_retriever=SimpleNamespace(name="constraint"),
            candidate_source_factory=source_factory,
        )

        self.assertEqual(len(service.candidate_generator.sources), 0)
        self.assertIs(source_factory.calls[0]["runtime"], runtime)
        self.assertEqual(source_factory.calls[0]["constraint_retriever"].name, "constraint")


if __name__ == "__main__":
    unittest.main()

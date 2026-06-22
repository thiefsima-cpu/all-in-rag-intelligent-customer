from __future__ import annotations

import unittest

from rag_modules.domain.shared.query_constraints import QueryConstraints
from rag_modules.query_understanding import QueryPlan
from rag_modules.retrieval.candidate_generator import RetrievalCandidateGenerator
from rag_modules.retrieval.candidate_sources import CandidateSourceSpec
from rag_modules.retrieval.contracts import EvidenceDocument, RetrievalRequest


class _StubSource:
    def __init__(self, spec: CandidateSourceSpec, documents) -> None:
        self.spec = spec
        self.documents = list(documents)
        self.requests = []

    def retrieve(self, request: RetrievalRequest):
        self.requests.append(request)
        return list(self.documents)


class _FailingSource:
    def __init__(self, spec: CandidateSourceSpec, exc: Exception | None = None) -> None:
        self.spec = spec
        self.exc = exc or TimeoutError(f"{spec.name} timeout")
        self.requests = []

    def retrieve(self, request: RetrievalRequest):
        self.requests.append(request)
        raise self.exc


class RetrievalCandidateGeneratorTests(unittest.TestCase):
    def test_generate_calibrates_request_and_normalizes_source_metadata(self) -> None:
        plan = QueryPlan(
            query="recommend tofu dishes",
            entity_keywords=["tofu"],
            source_entities=["mapo tofu"],
            topic_keywords=["spicy"],
            constraints=QueryConstraints(max_cook_minutes=30),
        )
        request = RetrievalRequest.from_inputs(
            query="recommend tofu dishes",
            top_k=3,
            candidate_k=5,
            query_plan=plan,
        )
        sources = [
            _StubSource(
                CandidateSourceSpec(
                    name="vector",
                    rank_name="vector",
                    search_method="vector",
                    search_type="vector_enhanced",
                    rank_order=2,
                ),
                [EvidenceDocument(content="vector-doc", recipe_name="V")],
            ),
            _StubSource(
                CandidateSourceSpec(
                    name="constraints",
                    rank_name="constraints",
                    search_method="constraints",
                    search_type="constraint_recipe",
                    rank_order=0,
                ),
                [EvidenceDocument(content="constraint-doc", recipe_name="C")],
            ),
            _StubSource(
                CandidateSourceSpec(
                    name="dual",
                    rank_name="dual_level",
                    search_method="dual_level",
                    search_type="dual_level",
                    rank_order=1,
                ),
                [EvidenceDocument(content="dual-doc", recipe_name="D")],
            ),
            _StubSource(
                CandidateSourceSpec(
                    name="bm25",
                    rank_name="bm25",
                    search_method="bm25",
                    search_type="bm25",
                    rank_order=3,
                ),
                [EvidenceDocument(content="bm25-doc", recipe_name="B")],
            ),
        ]
        generator = RetrievalCandidateGenerator(sources=sources)

        candidate_set = generator.generate(request)

        calibrated_request = sources[0].requests[0]
        self.assertEqual(
            calibrated_request.entity_keywords,
            ["tofu", "mapo tofu"],
        )
        self.assertEqual(calibrated_request.topic_keywords, ["spicy"])
        self.assertEqual(calibrated_request.constraints.max_cook_minutes, 30)
        self.assertEqual(candidate_set.stats["constraints"], 1)
        self.assertEqual(candidate_set.stats["dual"], 1)
        self.assertEqual(
            [name for name, _ in candidate_set.ranked_lists],
            ["constraints", "dual_level", "vector", "bm25"],
        )
        self.assertEqual(
            candidate_set.vector_docs[0].metadata["search_method"],
            "vector",
        )
        self.assertEqual(
            candidate_set.constraint_docs[0].metadata["search_type"],
            "constraint_recipe",
        )

    def test_generate_degrades_failed_source_and_continues_later_sources(self) -> None:
        failing = _FailingSource(
            CandidateSourceSpec(
                name="vector",
                rank_name="vector",
                search_method="vector",
                search_type="vector_enhanced",
                rank_order=1,
            ),
            TimeoutError("vector timed out"),
        )
        bm25 = _StubSource(
            CandidateSourceSpec(
                name="bm25",
                rank_name="bm25",
                search_method="bm25",
                search_type="bm25",
                rank_order=2,
            ),
            [EvidenceDocument(content="bm25-doc", recipe_name="B")],
        )
        generator = RetrievalCandidateGenerator(sources=[failing, bm25])

        candidate_set = generator.generate(
            RetrievalRequest.from_inputs(query="recommend tofu", top_k=2, candidate_k=4)
        )

        self.assertEqual(candidate_set.stats, {"vector": 0, "bm25": 1})
        self.assertEqual(candidate_set.degraded_sources, ["vector"])
        self.assertEqual(candidate_set.degraded_details[0]["reason"], "exception")
        self.assertEqual(candidate_set.degraded_details[0]["error_type"], "TimeoutError")
        self.assertEqual(candidate_set.degraded_details[0]["circuit_state"], "open")
        self.assertEqual(len(bm25.requests), 1)

    def test_configured_failure_threshold_delays_open_circuit(self) -> None:
        vector = _FailingSource(
            CandidateSourceSpec(
                name="vector",
                rank_name="vector",
                search_method="vector",
                search_type="vector_enhanced",
                rank_order=1,
            ),
            TimeoutError("vector timed out"),
        )
        bm25 = _StubSource(
            CandidateSourceSpec(
                name="bm25",
                rank_name="bm25",
                search_method="bm25",
                search_type="bm25",
                rank_order=2,
            ),
            [EvidenceDocument(content="bm25-doc", recipe_name="B")],
        )
        generator = RetrievalCandidateGenerator(
            sources=[vector, bm25],
            source_failure_threshold=2,
        )
        request = RetrievalRequest.from_inputs(query="recommend tofu", top_k=2, candidate_k=4)

        first = generator.generate(request)
        second = generator.generate(request)
        third = generator.generate(request)

        self.assertEqual(len(vector.requests), 2)
        self.assertEqual(len(bm25.requests), 3)
        self.assertEqual(first.degraded_details[0]["reason"], "exception")
        self.assertEqual(first.degraded_details[0]["circuit_state"], "closed")
        self.assertEqual(first.degraded_details[0]["failure_count"], 1)
        self.assertEqual(second.degraded_details[0]["reason"], "exception")
        self.assertEqual(second.degraded_details[0]["circuit_state"], "open")
        self.assertEqual(third.degraded_details[0]["reason"], "circuit_open")

    def test_fail_fast_strategy_raises_source_exception_and_stops_later_sources(self) -> None:
        vector = _FailingSource(
            CandidateSourceSpec(
                name="vector",
                rank_name="vector",
                search_method="vector",
                search_type="vector_enhanced",
                rank_order=1,
            ),
            TimeoutError("vector timed out"),
        )
        bm25 = _StubSource(
            CandidateSourceSpec(
                name="bm25",
                rank_name="bm25",
                search_method="bm25",
                search_type="bm25",
                rank_order=2,
            ),
            [EvidenceDocument(content="bm25-doc", recipe_name="B")],
        )
        generator = RetrievalCandidateGenerator(
            sources=[vector, bm25],
            source_degradation_strategy="fail_fast",
        )
        request = RetrievalRequest.from_inputs(query="recommend tofu", top_k=2, candidate_k=4)

        with self.assertRaisesRegex(TimeoutError, "vector timed out"):
            generator.generate(request)

        self.assertEqual(len(vector.requests), 1)
        self.assertEqual(len(bm25.requests), 0)

    def test_open_circuit_skips_only_the_failed_source(self) -> None:
        vector = _FailingSource(
            CandidateSourceSpec(
                name="vector",
                rank_name="vector",
                search_method="vector",
                search_type="vector_enhanced",
                rank_order=1,
            )
        )
        bm25 = _StubSource(
            CandidateSourceSpec(
                name="bm25",
                rank_name="bm25",
                search_method="bm25",
                search_type="bm25",
                rank_order=2,
            ),
            [EvidenceDocument(content="bm25-doc", recipe_name="B")],
        )
        generator = RetrievalCandidateGenerator(sources=[vector, bm25])
        request = RetrievalRequest.from_inputs(query="recommend tofu", top_k=2, candidate_k=4)

        generator.generate(request)
        second = generator.generate(request)

        self.assertEqual(len(vector.requests), 1)
        self.assertEqual(len(bm25.requests), 2)
        self.assertEqual(second.degraded_details[0]["reason"], "circuit_open")
        self.assertEqual(second.bm25_docs[0].recipe_name, "B")

    def test_request_skip_metadata_does_not_touch_source_or_circuit(self) -> None:
        vector = _StubSource(
            CandidateSourceSpec(
                name="vector",
                rank_name="vector",
                search_method="vector",
                search_type="vector_enhanced",
                rank_order=1,
            ),
            [EvidenceDocument(content="vector-doc", recipe_name="V")],
        )
        bm25 = _StubSource(
            CandidateSourceSpec(
                name="bm25",
                rank_name="bm25",
                search_method="bm25",
                search_type="bm25",
                rank_order=2,
            ),
            [EvidenceDocument(content="bm25-doc", recipe_name="B")],
        )
        request = RetrievalRequest.from_inputs(
            query="recommend tofu",
            top_k=2,
            candidate_k=4,
            metadata={"skip_candidate_sources": ["vector"]},
        )
        generator = RetrievalCandidateGenerator(sources=[vector, bm25])

        candidate_set = generator.generate(request)

        self.assertEqual(len(vector.requests), 0)
        self.assertEqual(len(bm25.requests), 1)
        self.assertEqual(candidate_set.vector_docs, [])
        self.assertEqual(candidate_set.degraded_details[0]["reason"], "request_skip")
        self.assertEqual(candidate_set.to_stage_details()["candidate_counts"]["bm25"], 1)
        self.assertEqual(candidate_set.to_stage_details()["degraded_sources"], ["vector"])


if __name__ == "__main__":
    unittest.main()

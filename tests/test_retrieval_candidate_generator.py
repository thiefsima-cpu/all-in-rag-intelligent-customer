from __future__ import annotations

import unittest

from rag_modules.query_constraints import QueryConstraints
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


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import unittest

from rag_modules.evaluation import (
    estimate_token_cost,
    grounding_metrics,
    percentile,
    retrieval_metrics,
)
from scripts.eval_queries import calculate_eval_metrics


class EvaluationMetricTests(unittest.TestCase):
    def test_retrieval_metrics_support_binary_and_graded_relevance(self) -> None:
        binary = retrieval_metrics(
            ["noise", "recipe-b", "recipe-a"],
            ["recipe-a", "recipe-b"],
            k=3,
        )
        graded = retrieval_metrics(
            ["recipe-b", "recipe-a"],
            {"recipe-a": 3.0, "recipe-b": 1.0},
            k=2,
        )

        self.assertEqual(binary["recall_at_k"], 1.0)
        self.assertEqual(binary["reciprocal_rank"], 0.5)
        self.assertGreater(binary["ndcg_at_k"], 0.0)
        self.assertLess(graded["ndcg_at_k"], 1.0)

        duplicate = retrieval_metrics(
            ["recipe-a", "recipe-a", "recipe-b"],
            {"recipe-a": 3.0, "recipe-b": 1.0},
            k=2,
        )
        self.assertEqual(duplicate["ndcg_at_k"], 1.0)

    def test_grounding_metrics_score_support_and_citation_validity(self) -> None:
        metrics = grounding_metrics(
            ("Tofu provides protein. Evidence 1. The moon is made of cheese. Evidence 3."),
            [
                {
                    "content": "Tofu is a protein-rich ingredient.",
                    "evidence_units": [
                        {"claim": "Tofu provides protein."},
                    ],
                }
            ],
        )

        self.assertEqual(metrics["claim_count"], 2)
        self.assertEqual(metrics["supported_claim_count"], 1)
        self.assertEqual(metrics["faithfulness"], 0.5)
        self.assertEqual(metrics["citation_accuracy"], 0.5)
        self.assertEqual(metrics["citation_coverage"], 1.0)

    def test_percentile_and_token_cost_are_deterministic(self) -> None:
        self.assertEqual(percentile([1, 2, 3, 4, 100], 0.95), 100.0)
        self.assertEqual(
            estimate_token_cost(
                prompt_tokens=1_000,
                completion_tokens=500,
                input_cost_per_million_tokens=2.0,
                output_cost_per_million_tokens=4.0,
            ),
            0.004,
        )

    def test_report_aggregation_includes_quality_latency_and_cost(self) -> None:
        metrics = calculate_eval_metrics(
            [
                {
                    "passed": True,
                    "category": "test",
                    "evaluation": {
                        "expected_strategy": "hybrid",
                        "strategy": "hybrid",
                        "expected_recipe_names": ["a"],
                        "answer_checked": True,
                        "answer_passed": True,
                        "answer_preview": "Evidence 1",
                    },
                    "retrieval": {
                        "missing_recipe_names": [],
                        "recall_at_k": 1.0,
                        "reciprocal_rank": 0.5,
                        "ndcg_at_k": 0.75,
                        "evidence": [],
                    },
                    "grounding": {
                        "faithfulness": 0.8,
                        "citation_accuracy": 1.0,
                    },
                    "runtime": {"latency_ms": 125.0},
                    "cost": {
                        "prompt_tokens": 10,
                        "completion_tokens": 5,
                        "total_tokens": 15,
                        "estimated_cost_usd": 0.001,
                    },
                }
            ]
        )

        self.assertEqual(metrics["recall_at_k"], 1.0)
        self.assertEqual(metrics["mrr"], 0.5)
        self.assertEqual(metrics["ndcg_at_k"], 0.75)
        self.assertEqual(metrics["faithfulness"], 0.8)
        self.assertEqual(metrics["citation_accuracy"], 1.0)
        self.assertEqual(metrics["p95_latency_ms"], 125.0)
        self.assertEqual(metrics["total_tokens"], 15)
        self.assertEqual(metrics["estimated_cost_usd"], 0.001)

    def test_report_aggregation_includes_fallback_and_degraded_sources(self) -> None:
        metrics = calculate_eval_metrics(
            [
                {
                    "passed": True,
                    "category": "test",
                    "evaluation": {"answer_checked": True, "answer_preview": "Evidence 1"},
                    "retrieval": {"evidence": []},
                    "grounding": {},
                    "runtime": {"latency_ms": 100.0},
                    "cost": {},
                    "resilience": {
                        "fallback_used": True,
                        "fallback_reasons": [
                            "two_stage_to_direct_model",
                            "graph_empty_to_hybrid",
                        ],
                        "retrieval_degraded": True,
                        "degraded_sources": ["vector"],
                    },
                },
                {
                    "passed": True,
                    "category": "test",
                    "evaluation": {"answer_checked": True, "answer_preview": "Evidence 1"},
                    "retrieval": {"evidence": []},
                    "grounding": {},
                    "runtime": {"latency_ms": 125.0},
                    "cost": {},
                    "resilience": {
                        "fallback_used": False,
                        "fallback_reasons": [],
                        "retrieval_degraded": False,
                        "degraded_sources": [],
                    },
                },
            ]
        )

        self.assertEqual(metrics["fallback_case_count"], 1)
        self.assertEqual(metrics["fallback_rate"], 0.5)
        self.assertEqual(
            metrics["fallback_reasons"],
            {"graph_empty_to_hybrid": 1, "two_stage_to_direct_model": 1},
        )
        self.assertEqual(metrics["retrieval_degraded_case_count"], 1)
        self.assertEqual(metrics["retrieval_degradation_rate"], 0.5)
        self.assertEqual(metrics["degraded_sources"], ["vector"])
        self.assertEqual(metrics["degraded_source_counts"], {"vector": 1})


if __name__ == "__main__":
    unittest.main()

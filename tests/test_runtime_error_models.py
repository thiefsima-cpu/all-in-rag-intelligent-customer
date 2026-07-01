from __future__ import annotations

import json
import unittest

from rag_modules.generation.clients.errors import (
    GenerationLatencyBudgetExceeded,
    GenerationProviderResponseError,
)
from rag_modules.runtime import RuntimeErrorDetail
from rag_modules.runtime.error_models import (
    answer_error_detail,
    generation_error_detail,
    retrieval_error_detail,
    routing_error_detail,
    runtime_error_detail,
)


class RuntimeErrorDetailTests(unittest.TestCase):
    def test_runtime_error_detail_serializes_only_code_and_safe_detail(self) -> None:
        secret = "provider-secret-payload"

        detail = runtime_error_detail(
            code="ANSWER_FAILED",
            detail="answer_failed",
            error=RuntimeError(secret),
        )

        self.assertIsInstance(detail, RuntimeErrorDetail)
        self.assertEqual(detail.to_dict(), {"code": "ANSWER_FAILED", "detail": "answer_failed"})
        self.assertNotIn(secret, json.dumps(detail.to_dict()))

    def test_generation_errors_are_classified_without_exception_text(self) -> None:
        secret = "upstream token abc123"

        cases = [
            (
                TimeoutError(secret),
                {"code": "GENERATION_PROVIDER_TIMEOUT", "detail": "generation_provider_timeout"},
            ),
            (
                GenerationLatencyBudgetExceeded(secret),
                {
                    "code": "GENERATION_LATENCY_BUDGET_EXCEEDED",
                    "detail": "generation_latency_budget_exceeded",
                },
            ),
            (
                GenerationProviderResponseError(
                    secret,
                    failure_code="generation_provider_empty_choices",
                ),
                {
                    "code": "GENERATION_PROVIDER_EMPTY_CHOICES",
                    "detail": "generation_provider_empty_choices",
                },
            ),
            (
                RuntimeError(secret),
                {"code": "GENERATION_PROVIDER_ERROR", "detail": "generation_provider_error"},
            ),
        ]

        for error, expected in cases:
            with self.subTest(expected=expected):
                detail = generation_error_detail(error)
                self.assertEqual(detail.to_dict(), expected)
                self.assertNotIn(secret, json.dumps(detail.to_dict()))

    def test_subsystem_helpers_return_stable_safe_details(self) -> None:
        secret = "database://user:password@internal"

        self.assertEqual(
            retrieval_error_detail("exception", RuntimeError(secret)).to_dict(),
            {
                "code": "CANDIDATE_SOURCE_RETRIEVAL_FAILED",
                "detail": "candidate_source_retrieval_failed",
            },
        )
        self.assertEqual(
            retrieval_error_detail("circuit_open").to_dict(),
            {
                "code": "CANDIDATE_SOURCE_CIRCUIT_OPEN",
                "detail": "candidate_source_circuit_open",
            },
        )
        self.assertEqual(
            routing_error_detail(RuntimeError(secret)).to_dict(),
            {"code": "QUERY_PROCESSING_FAILED", "detail": "query_processing_failed"},
        )
        self.assertEqual(
            answer_error_detail(RuntimeError(secret)).to_dict(),
            {"code": "ANSWER_FAILED", "detail": "answer_failed"},
        )


if __name__ == "__main__":
    unittest.main()

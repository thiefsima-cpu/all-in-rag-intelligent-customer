from __future__ import annotations

import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

from rag_modules.app.services.answer_models import QuestionAnswerResult
from rag_modules.app.services.answer_pipeline import NO_EVIDENCE_ANSWER
from rag_modules.app.services.question_answer_service import QuestionAnswerService
from rag_modules.configuration.testing import build_test_config
from rag_modules.observability.tracing import QueryTracer
from rag_modules.retrieval.contracts import EvidenceDocument
from rag_modules.runtime import (
    GenerationSnapshot,
    GraphRetrievalSnapshot,
    QueryAnalysis,
    QueryTraceEvent,
    QueryUnderstandingSnapshot,
    RetrievalOutcome,
    RouteResolution,
    RouteSnapshot,
    RouteStageSnapshot,
    SearchStrategy,
)


def _build_resolution(
    question: str,
    *,
    documents: list[EvidenceDocument] | None = None,
    strategy: SearchStrategy = SearchStrategy.HYBRID_TRADITIONAL,
) -> RouteResolution:
    analysis = QueryAnalysis(
        query_complexity=0.84 if strategy != SearchStrategy.HYBRID_TRADITIONAL else 0.24,
        relationship_intensity=0.79 if strategy != SearchStrategy.HYBRID_TRADITIONAL else 0.22,
        reasoning_required=strategy != SearchStrategy.HYBRID_TRADITIONAL,
        entity_count=3,
        recommended_strategy=strategy,
        confidence=0.91,
        reasoning="test",
    )
    understanding = QueryUnderstandingSnapshot(
        query=question,
        analysis=analysis,
    )
    retrieval = RetrievalOutcome(
        query=question,
        strategy=strategy.value,
        evidence_documents=list(documents or []),
    )
    return RouteResolution(
        understanding=understanding,
        retrieval=retrieval,
    )


class _FakeQueryTracer:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def record(self, **kwargs) -> QueryTraceEvent:
        self.calls.append(kwargs)
        return QueryTraceEvent(
            query=kwargs["query"],
            error=str(kwargs.get("error") or ""),
        )


class _FakeGenerationService:
    def __init__(
        self,
        *,
        answer: str = "final answer",
        stream_chunks: list[str] | None = None,
        stream_error: Exception | None = None,
        trace: GenerationSnapshot | None = None,
        stream_trace: GenerationSnapshot | None = None,
    ) -> None:
        self.answer = answer
        self.stream_chunks = list(stream_chunks or [])
        self.stream_error = stream_error
        self.trace = trace or GenerationSnapshot(
            mode="two_stage",
            total_evidence_items=2,
            selected_evidence_items=1,
        )
        self.stream_trace = stream_trace or GenerationSnapshot.from_dict(self.trace.to_dict())
        self.direct_calls = 0
        self.stream_calls = 0
        self.answer_contexts = []

    def generate_answer_from_context(self, answer_context):
        self.direct_calls += 1
        self.answer_contexts.append(answer_context)
        return self.answer

    def generate_answer_with_trace_from_context(self, answer_context):
        self.direct_calls += 1
        self.answer_contexts.append(answer_context)
        return self.answer, self.trace

    def generate_answer_stream_from_context(self, answer_context):
        self.stream_calls += 1
        self.answer_contexts.append(answer_context)
        if self.stream_error:
            raise self.stream_error
        for chunk in self.stream_chunks:
            yield chunk

    def generate_answer_stream_with_trace_from_context(
        self,
        answer_context,
        *,
        max_retries=None,
        chunk_callback=None,
    ):
        del max_retries
        self.stream_calls += 1
        self.answer_contexts.append(answer_context)
        if self.stream_error:
            raise self.stream_error
        for chunk in self.stream_chunks:
            if chunk_callback:
                chunk_callback(chunk)
        return (
            "".join(self.stream_chunks).strip() or "Streaming output completed",
            self.stream_trace,
        )


class _FakeQueryRouter:
    def __init__(
        self,
        *,
        resolution: RouteResolution | None = None,
        route_trace: RouteSnapshot | None = None,
        graph_trace: GraphRetrievalSnapshot | None = None,
        route_error: Exception | None = None,
    ) -> None:
        question = resolution.query if resolution else ""
        strategy = resolution.analysis.strategy_name if resolution else ""
        self.resolution = resolution
        self.route_error = route_error
        self.route_trace = route_trace or RouteSnapshot(query=question, strategy=strategy)
        self.graph_trace = graph_trace or GraphRetrievalSnapshot()
        self.route_calls: list[tuple[str, int]] = []

    def route(self, question: str, top_k: int):
        self.route_calls.append((question, top_k))
        if self.route_error:
            raise self.route_error
        return self.resolution

    def route_with_trace(self, question: str, top_k: int):
        resolution = self.route(question, top_k)
        route_trace = RouteSnapshot.from_dict(self.route_trace.to_dict())
        if self.graph_trace.has_content() and route_trace.strategy in {"graph_rag", "combined"}:
            if route_trace.strategy == "combined":
                route_trace.add_stage(
                    "combined",
                    RouteStageSnapshot(
                        doc_count=self.graph_trace.doc_count,
                        details={"graph_trace": self.graph_trace.to_dict()},
                    ),
                )
            else:
                route_trace.add_stage(
                    "graph_rag",
                    RouteStageSnapshot(
                        doc_count=self.graph_trace.doc_count,
                        details=self.graph_trace.to_stage_details(),
                    ),
                )
        return resolution, route_trace

    def explain_routing_decision(self, question: str) -> str:
        return f"explain:{question}"


class _CapturingWorkflow:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def answer_question(self, **kwargs):
        self.calls.append(kwargs)
        return QuestionAnswerServiceTests.make_result(kwargs["question"])


class QuestionAnswerServiceTests(unittest.TestCase):
    @staticmethod
    def make_result(question: str) -> QuestionAnswerResult:
        return QuestionAnswerResult(answer=f"result:{question}", analysis=None)

    def setUp(self) -> None:
        self.config = build_test_config()

    def test_no_evidence_returns_fallback_and_records_trace(self) -> None:
        question = "Which recipe connects tofu and fermented bean paste?"
        router = _FakeQueryRouter(
            resolution=_build_resolution(question, documents=[]),
            route_trace=RouteSnapshot(query=question, strategy="hybrid_traditional"),
            graph_trace=GraphRetrievalSnapshot(query=question, doc_count=2),
        )
        generation = _FakeGenerationService()
        tracer = _FakeQueryTracer()
        messages: list[str] = []
        service = QuestionAnswerService(self.config, router, generation, tracer)

        result = service.answer_question(
            question,
            explain_routing=True,
            message_callback=messages.append,
        )

        self.assertEqual(result.answer, NO_EVIDENCE_ANSWER)
        self.assertEqual(generation.direct_calls, 0)
        self.assertEqual(len(tracer.calls), 1)
        self.assertEqual(result.graph_trace.doc_count, 0)
        self.assertEqual(result.trace_event.query, question)
        self.assertIn("Running query routing...", messages)

    def test_successful_answer_captures_route_graph_and_generation_traces(self) -> None:
        question = "Trace the ingredient substitution path for mapo tofu."
        documents = [
            EvidenceDocument(
                content="doc one",
                recipe_name="mapo tofu",
                search_type="graph",
                score=0.91,
            )
        ]
        router = _FakeQueryRouter(
            resolution=_build_resolution(
                question,
                documents=documents,
                strategy=SearchStrategy.COMBINED,
            ),
            route_trace=RouteSnapshot(query=question, strategy="combined"),
            graph_trace=GraphRetrievalSnapshot(
                query=question,
                strategy="combined",
                doc_count=1,
                path_count=2,
            ),
        )
        generation = _FakeGenerationService(
            answer="The graph evidence points to a chili-bean-paste substitution chain.",
            trace=GenerationSnapshot(
                mode="two_stage",
                total_evidence_items=3,
                selected_evidence_items=2,
            ),
        )
        tracer = _FakeQueryTracer()
        service = QuestionAnswerService(self.config, router, generation, tracer)

        result = service.answer_question(question)

        self.assertIn("substitution chain", result.answer)
        self.assertEqual(generation.direct_calls, 1)
        self.assertEqual(result.route_trace.strategy, "combined")
        self.assertEqual(result.graph_trace.doc_count, 1)
        self.assertEqual(result.generation_trace.mode, "two_stage")
        self.assertEqual(result.answer_context.question, question)
        self.assertEqual(result.trace_event.query, question)
        response = result.to_response()
        payload = response.to_dict()
        self.assertEqual(response.strategy, "combined")
        self.assertEqual(response.doc_count, 1)
        self.assertTrue(response.has_evidence)
        self.assertEqual(response.trace_event["query"], question)
        self.assertEqual(set(payload.keys()), {"summary", "grounding", "diagnostics", "traces"})
        self.assertEqual(payload["summary"]["answer"], response.answer)
        self.assertEqual(payload["summary"]["strategy"], "combined")
        self.assertEqual(
            payload["grounding"]["route_resolution"]["understanding"]["analysis"][
                "recommended_strategy"
            ],
            "combined",
        )
        self.assertEqual(payload["grounding"]["evidence_documents"][0]["recipe_name"], "mapo tofu")
        self.assertEqual(payload["traces"]["route_trace"]["strategy"], "combined")
        self.assertEqual(payload["traces"]["graph_trace"]["doc_count"], 1)
        self.assertEqual(result.to_dict(), response.to_dict())

    def test_degraded_generation_status_is_exposed_in_response_summary(self) -> None:
        question = "Explain a relation with provider fallback."
        documents = [
            EvidenceDocument(
                content="grounded evidence",
                recipe_name="fallback recipe",
                search_type="graph",
                score=0.9,
            )
        ]
        generation = _FakeGenerationService(
            answer="evidence-only answer",
            trace=GenerationSnapshot(
                status="degraded",
                mode="two_stage",
                fallback_used=True,
                fallback_reason="generation_provider_empty_choices",
                failure_code="generation_provider_empty_choices",
                provider_latency_ms=123.0,
                total_evidence_items=1,
                selected_evidence_items=1,
            ),
        )
        service = QuestionAnswerService(
            self.config,
            _FakeQueryRouter(
                resolution=_build_resolution(
                    question,
                    documents=documents,
                    strategy=SearchStrategy.GRAPH_RAG,
                )
            ),
            generation,
            _FakeQueryTracer(),
        )

        response = service.answer_question_response(question)

        self.assertEqual(response.status, "degraded")
        self.assertTrue(response.fallback_used)
        self.assertEqual(
            response.failure_code,
            "generation_provider_empty_choices",
        )
        self.assertEqual(response.summary.provider_latency_ms, 123.0)

    def test_retrieval_degradation_is_exposed_in_response_diagnostics(self) -> None:
        question = "Explain with a degraded vector source."
        documents = [
            EvidenceDocument(
                content="grounded evidence",
                recipe_name="fallback recipe",
                search_type="hybrid",
                score=0.9,
            )
        ]
        route_trace = RouteSnapshot(
            query=question,
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
            },
            final_doc_count=1,
        )
        service = QuestionAnswerService(
            self.config,
            _FakeQueryRouter(
                resolution=_build_resolution(question, documents=documents),
                route_trace=route_trace,
            ),
            _FakeGenerationService(
                answer="grounded degraded-source answer",
                trace=GenerationSnapshot(status="success", mode="direct"),
            ),
            QueryTracer(self.config),
        )

        response = service.answer_question_response(question)
        diagnostics = response.diagnostic_payload

        self.assertTrue(diagnostics["retrieval_degraded"])
        self.assertEqual(diagnostics["degraded_sources"], ["vector"])
        self.assertTrue(diagnostics["circuit_breaker_triggered"])
        self.assertFalse(diagnostics["answer_impacted"])
        self.assertEqual(diagnostics["degraded_candidates"][0]["reason"], "circuit_open")

    def test_result_uses_request_scoped_route_trace_over_router_last_trace(self) -> None:
        question = "Explain the active route trace."
        documents = [
            EvidenceDocument(
                content="doc one",
                recipe_name="active recipe",
                search_type="graph",
                score=0.88,
            )
        ]
        resolution = _build_resolution(
            question,
            documents=documents,
            strategy=SearchStrategy.COMBINED,
        )
        resolution.metadata["route_trace"] = RouteSnapshot(
            query=question,
            strategy="combined",
            stages={
                "combined": {
                    "doc_count": 1,
                    "graph_doc_count": 1,
                    "traditional_doc_count": 1,
                }
            },
        ).to_dict()
        router = _FakeQueryRouter(
            resolution=resolution,
            route_trace=RouteSnapshot(query="stale-question", strategy="hybrid_traditional"),
            graph_trace=GraphRetrievalSnapshot(query="stale-question", doc_count=99),
        )
        router.route_with_trace = lambda q, top_k: (
            router.resolution,
            RouteSnapshot.from_dict(resolution.metadata["route_trace"]),
        )
        generation = _FakeGenerationService(answer="scoped answer")
        tracer = _FakeQueryTracer()
        service = QuestionAnswerService(self.config, router, generation, tracer)

        result = service.answer_question(question)

        self.assertEqual(result.route_trace.query, question)
        self.assertEqual(result.route_trace.strategy, "combined")
        self.assertEqual(result.graph_trace.doc_count, 1)
        self.assertNotEqual(result.route_trace.query, "stale-question")

    def test_result_uses_explicit_route_and_generation_traces_when_available(self) -> None:
        question = "Use explicit trace interfaces."
        documents = [EvidenceDocument(content="doc", recipe_name="recipe", search_type="graph")]
        router = _FakeQueryRouter(
            resolution=_build_resolution(question, documents=documents),
            route_trace=RouteSnapshot(query=question, strategy="combined"),
            graph_trace=GraphRetrievalSnapshot(query=question, doc_count=1),
        )
        router.route_with_trace = lambda q, top_k: (
            router.resolution,
            RouteSnapshot(query=q, strategy="combined"),
        )
        generation = _FakeGenerationService(
            answer="explicit trace answer",
            trace=GenerationSnapshot(mode="direct", total_evidence_items=1),
        )
        tracer = _FakeQueryTracer()
        service = QuestionAnswerService(self.config, router, generation, tracer)

        result = service.answer_question(question)

        self.assertEqual(result.route_trace.query, question)
        self.assertEqual(result.generation_trace.mode, "direct")
        self.assertEqual(result.answer, "explicit trace answer")

    def test_streaming_success_returns_joined_chunks(self) -> None:
        question = "Summarize the sauce adjustments."
        documents = [EvidenceDocument(content="doc", recipe_name="recipe", search_type="hybrid")]
        router = _FakeQueryRouter(
            resolution=_build_resolution(question, documents=documents),
        )
        generation = _FakeGenerationService(
            stream_chunks=["part one", " and part two"],
        )
        tracer = _FakeQueryTracer()
        chunks: list[str] = []
        service = QuestionAnswerService(self.config, router, generation, tracer)

        result = service.answer_question(
            question,
            stream=True,
            chunk_callback=chunks.append,
        )

        self.assertEqual(result.answer, "part one and part two")
        self.assertEqual(generation.stream_calls, 1)
        self.assertEqual(generation.direct_calls, 0)
        self.assertEqual(chunks, ["part one", " and part two", "\n"])

    def test_streaming_prefers_explicit_request_trace_over_stale_last_trace(self) -> None:
        question = "Summarize the sauce adjustments with explicit trace."
        documents = [EvidenceDocument(content="doc", recipe_name="recipe", search_type="hybrid")]
        router = _FakeQueryRouter(
            resolution=_build_resolution(question, documents=documents),
        )
        generation = _FakeGenerationService(
            stream_chunks=["part one", " and part two"],
            trace=GenerationSnapshot(mode="stale", total_evidence_items=9),
            stream_trace=GenerationSnapshot(mode="direct", total_evidence_items=2),
        )
        tracer = _FakeQueryTracer()
        service = QuestionAnswerService(self.config, router, generation, tracer)

        result = service.answer_question(
            question,
            stream=True,
        )

        self.assertEqual(result.answer, "part one and part two")
        self.assertEqual(result.generation_trace.mode, "direct")
        self.assertEqual(result.generation_trace.total_evidence_items, 2)

    def test_streaming_failure_falls_back_to_standard_generation(self) -> None:
        question = "Explain the graph evidence."
        documents = [EvidenceDocument(content="doc", recipe_name="recipe", search_type="graph")]
        router = _FakeQueryRouter(
            resolution=_build_resolution(question, documents=documents),
        )
        generation = _FakeGenerationService(
            answer="fallback answer",
            stream_error=RuntimeError("stream failed"),
        )
        tracer = _FakeQueryTracer()
        messages: list[str] = []
        service = QuestionAnswerService(self.config, router, generation, tracer)

        result = service.answer_question(
            question,
            stream=True,
            message_callback=messages.append,
        )

        self.assertEqual(result.answer, "fallback answer")
        self.assertEqual(generation.stream_calls, 1)
        self.assertEqual(generation.direct_calls, 1)
        self.assertTrue(any("Falling back to standard mode" in message for message in messages))

    def test_concurrent_requests_keep_all_traces_request_scoped(self) -> None:
        route_barrier = threading.Barrier(2)
        generation_barrier = threading.Barrier(2)

        class _ConcurrentRouter:
            @staticmethod
            def explain_routing_decision(question: str) -> str:
                return question

            def route_with_trace(self, question: str, top_k: int):
                document = EvidenceDocument(
                    content=f"evidence:{question}",
                    recipe_name=question,
                    search_type="graph",
                )
                resolution = _build_resolution(
                    question,
                    documents=[document],
                    strategy=SearchStrategy.COMBINED,
                )
                graph_trace = GraphRetrievalSnapshot(
                    query=question,
                    doc_count=1,
                    path_count=1,
                    retrieval_plan={"request": question},
                )
                route_trace = RouteSnapshot(
                    query=question,
                    strategy="combined",
                    requested_top_k=top_k,
                )
                route_trace.add_stage(
                    "combined",
                    RouteStageSnapshot(
                        doc_count=1,
                        details={"graph_trace": graph_trace.to_dict()},
                    ),
                )
                route_barrier.wait(timeout=2.0)
                return resolution, route_trace

        class _ConcurrentGeneration:
            def generate_answer_with_trace_from_context(self, answer_context):
                question = answer_context.question
                generation_barrier.wait(timeout=2.0)
                request_number = 1 if question == "concurrent-one" else 2
                return (
                    f"answer:{question}",
                    GenerationSnapshot(
                        status="success",
                        mode="direct" if request_number == 1 else "two_stage",
                        total_evidence_items=request_number,
                        selected_evidence_items=request_number,
                    ),
                )

        service = QuestionAnswerService(
            self.config,
            _ConcurrentRouter(),
            _ConcurrentGeneration(),
            _FakeQueryTracer(),
        )
        questions = ("concurrent-one", "concurrent-two")

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = {
                question: executor.submit(service.answer_question, question)
                for question in questions
            }
            results = {question: future.result(timeout=3.0) for question, future in futures.items()}

        first = results["concurrent-one"]
        second = results["concurrent-two"]
        self.assertEqual(first.answer, "answer:concurrent-one")
        self.assertEqual(first.route_trace.query, "concurrent-one")
        self.assertEqual(first.graph_trace.query, "concurrent-one")
        self.assertEqual(first.graph_trace.retrieval_plan["request"], "concurrent-one")
        self.assertEqual(first.generation_trace.mode, "direct")
        self.assertEqual(first.generation_trace.total_evidence_items, 1)
        self.assertEqual(second.answer, "answer:concurrent-two")
        self.assertEqual(second.route_trace.query, "concurrent-two")
        self.assertEqual(second.graph_trace.query, "concurrent-two")
        self.assertEqual(second.graph_trace.retrieval_plan["request"], "concurrent-two")
        self.assertEqual(second.generation_trace.mode, "two_stage")
        self.assertEqual(second.generation_trace.total_evidence_items, 2)

    def test_legacy_services_do_not_leak_shared_trace_state(self) -> None:
        question = "Use legacy services."
        documents = [EvidenceDocument(content="doc", recipe_name="recipe", search_type="graph")]
        resolution = _build_resolution(
            question,
            documents=documents,
            strategy=SearchStrategy.COMBINED,
        )

        class _LegacyRouter:
            def __init__(self) -> None:
                self.last_trace = RouteSnapshot(query=question, strategy="combined")
                self.graph_rag_retrieval = SimpleNamespace(
                    last_trace=GraphRetrievalSnapshot(query=question, doc_count=1, path_count=2)
                )

            def route(self, query: str, top_k: int):
                del query, top_k
                return resolution

        class _LegacyGeneration:
            def __init__(self) -> None:
                self.last_trace = GenerationSnapshot(mode="direct", total_evidence_items=1)

            def generate_answer_from_context(self, answer_context):
                self.answer_context = answer_context
                return "legacy answer"

        tracer = _FakeQueryTracer()
        service = QuestionAnswerService(
            self.config,
            _LegacyRouter(),
            _LegacyGeneration(),
            tracer,
        )

        result = service.answer_question(question)

        self.assertEqual(result.answer, "legacy answer")
        self.assertFalse(result.route_trace.has_content())
        self.assertFalse(result.graph_trace.has_content())
        self.assertFalse(result.generation_trace.is_recorded())

    def test_route_exception_returns_error_result_and_trace(self) -> None:
        question = "Trigger router failure."
        router = _FakeQueryRouter(
            route_error=RuntimeError("router exploded"),
            route_trace=RouteSnapshot(query=question, error="router exploded"),
        )
        generation = _FakeGenerationService()
        tracer = _FakeQueryTracer()
        service = QuestionAnswerService(self.config, router, generation, tracer)

        result = service.answer_question(question)

        self.assertIn("router exploded", result.answer)
        self.assertIsNone(result.analysis)
        self.assertEqual(len(tracer.calls), 1)
        self.assertEqual(result.trace_event.error, "router exploded")

    def test_question_answer_service_delegates_to_injected_workflow(self) -> None:
        workflow = _CapturingWorkflow()
        service = QuestionAnswerService(
            self.config,
            query_router=SimpleNamespace(),
            generation_module=SimpleNamespace(),
            query_tracer=SimpleNamespace(),
            answer_workflow=workflow,
        )

        result = service.answer_question(
            "delegated question",
            stream=True,
            explain_routing=True,
        )

        self.assertEqual(result.answer, "result:delegated question")
        self.assertEqual(len(workflow.calls), 1)
        self.assertTrue(workflow.calls[0]["stream"])
        self.assertTrue(workflow.calls[0]["explain_routing"])

    def test_question_answer_service_response_falls_back_to_result_response(self) -> None:
        workflow = _CapturingWorkflow()
        service = QuestionAnswerService(
            self.config,
            query_router=SimpleNamespace(),
            generation_module=SimpleNamespace(),
            query_tracer=SimpleNamespace(),
            answer_workflow=workflow,
        )

        response = service.answer_question_response("delegated question")
        payload = response.to_dict()

        self.assertEqual(response.answer, "result:delegated question")
        self.assertEqual(response.strategy, "")
        self.assertEqual(payload["summary"]["answer"], "result:delegated question")
        self.assertEqual(payload["grounding"]["evidence_documents"], [])
        self.assertEqual(len(workflow.calls), 1)


if __name__ == "__main__":
    unittest.main()

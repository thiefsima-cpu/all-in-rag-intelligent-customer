from __future__ import annotations

import json
import threading
import time
import unittest

from fastapi.testclient import TestClient
from pydantic import ValidationError

from rag_modules.app.diagnostics import ArtifactManifestDiagnostics, StartupDiagnostics
from rag_modules.artifacts import ARTIFACT_HEALTH_MISSING, ARTIFACT_HEALTH_READY
from rag_modules.configuration.testing import build_test_config
from rag_modules.interfaces.api import create_build_api_app, create_serving_api_app
from rag_modules.interfaces.api.models import (
    MAX_QUESTION_CHARS,
    AnswerResponseModel,
    AnswerStreamEventType,
)
from rag_modules.interfaces.api.service import (
    GraphRAGBuildApiService,
    GraphRAGServingApiService,
)
from rag_modules.retrieval.contracts import EvidenceDocument
from rag_modules.runtime import (
    AnswerContext,
    GenerationSnapshot,
    GraphRetrievalSnapshot,
    QueryAnalysis,
    QueryDiagnostics,
    QueryTraceEvent,
    RetrievalOutcome,
    RetrievalTraceSnapshot,
    RouteResolution,
    RouteSnapshot,
)

_API_TOKEN = "test-api-access-token"
_API_CONFIG = build_test_config({"api": {"access_token": _API_TOKEN}})


def _client(app: object) -> TestClient:
    return TestClient(
        app,
        headers={"Authorization": f"Bearer {_API_TOKEN}"},
    )


def _wait_for_job_status(
    client: TestClient,
    job_id: str,
    expected_status: str,
    *,
    timeout: float = 2.0,
) -> dict:
    deadline = time.time() + timeout
    last_payload: dict = {}
    while time.time() < deadline:
        response = client.get(f"/jobs/{job_id}")
        if response.status_code == 200:
            last_payload = response.json()["job"]
            if last_payload["status"] == expected_status:
                return last_payload
        time.sleep(0.02)
    raise AssertionError(
        f"Timed out waiting for build job {job_id} to reach {expected_status!r}. "
        f"Last payload: {last_payload}"
    )


def _wait_for_service_job_status(
    service: GraphRAGBuildApiService,
    job_id: str,
    expected_status: str,
    *,
    timeout: float = 2.0,
) -> dict:
    deadline = time.time() + timeout
    last_payload: dict = {}
    while time.time() < deadline:
        last_payload = service.get_build_job(job_id)
        if last_payload["status"] == expected_status:
            return last_payload
        time.sleep(0.02)
    raise AssertionError(
        f"Timed out waiting for build job {job_id} to reach {expected_status!r}. "
        f"Last payload: {last_payload}"
    )


def _diagnostics(
    *,
    mode: str,
    system_ready: bool,
    build_initialized: bool,
    serving_initialized: bool,
) -> StartupDiagnostics:
    return StartupDiagnostics(
        mode=mode,
        llm_model="qwen3.7-plus",
        embedding_model="qwen3-vl-embedding",
        rerank_model="qwen3-vl-rerank",
        trace_enabled=True,
        trace_path="storage/traces/query_trace.jsonl",
        trace_stats={"dropped_events": 0, "queued_events": 0, "async_enabled": True},
        build_initialized=build_initialized,
        serving_initialized=serving_initialized,
        artifacts_ready=system_ready,
        system_ready=system_ready,
        retrieval_engines_initialized=system_ready and serving_initialized,
        manifest=ArtifactManifestDiagnostics(
            stage="ready" if system_ready else "missing",
            health=ARTIFACT_HEALTH_READY if system_ready else ARTIFACT_HEALTH_MISSING,
            updated_at="",
            collection_name="recipes",
            manifest_path="storage/indexes/artifact_manifest.json",
            documents_path="storage/indexes/documents.json",
            chunks_path="storage/indexes/chunks.json",
            total_documents=2 if system_ready else 0,
            total_chunks=4 if system_ready else 0,
            vector_rows=4 if system_ready else 0,
            cache_hit=False,
            last_error="",
            build_metadata={},
        ),
    )


def _answer_payload(question: str, *, stream: bool = False) -> dict:
    route_trace = RouteSnapshot(
        query=question,
        strategy="hybrid_traditional",
        requested_top_k=5,
        total_latency_ms=3.5,
        final_doc_count=1,
    )
    evidence_document = EvidenceDocument(
        content="Mapo tofu is a tofu dish.",
        recipe_name="mapo tofu",
        score=0.93,
        search_type="hybrid",
        search_method="vector",
        source="vector",
        route_strategy="hybrid_traditional",
    )
    retrieval = RetrievalOutcome(
        query=question,
        strategy="hybrid_traditional",
        evidence_documents=[evidence_document],
        route_trace=route_trace,
    )
    analysis = QueryAnalysis(
        query_complexity=0.2,
        relationship_intensity=0.1,
        recommended_strategy="hybrid_traditional",
        confidence=0.8,
        reasoning="simple factual cooking question",
    )
    answer_context = AnswerContext(
        question=question,
        retrieval=retrieval,
        analysis=analysis,
        metadata={"stream": stream},
    )
    route_resolution = RouteResolution(
        retrieval=retrieval,
        metadata={"route_strategy": "hybrid_traditional"},
    )
    graph_trace = GraphRetrievalSnapshot()
    generation_trace = GenerationSnapshot(
        status="success",
        mode="direct",
        total_evidence_items=1,
        selected_evidence_items=1,
        total_latency_ms=4.2,
        provider_latency_ms=2.7,
        prompt_tokens=11,
        completion_tokens=7,
        total_tokens=18,
        estimated_cost_usd=0.001,
        token_usage_source="test",
    )
    diagnostics = QueryDiagnostics(
        retrieval_bucket="ok",
        generation_bucket="ok",
        overall_bucket="ok",
    )
    trace_event = QueryTraceEvent(
        query_id="trace-test",
        timestamp=1,
        query=question,
        strategy="hybrid_traditional",
        latency_ms=12.3,
        retrieval=RetrievalTraceSnapshot(
            doc_count=1,
            evidence=[evidence_document.to_dict()],
            route_trace=route_trace,
            graph_trace=graph_trace,
        ),
        generation=generation_trace,
        diagnostics=diagnostics,
    )

    return {
        "summary": {
            "answer": f"answer:{question}",
            "status": "success",
            "strategy": "hybrid_traditional",
            "latency_ms": 12.3,
            "doc_count": 1,
            "has_evidence": True,
            "fallback_used": False,
            "failure_code": "",
            "provider_latency_ms": generation_trace.provider_latency_ms,
            "prompt_tokens": generation_trace.prompt_tokens,
            "completion_tokens": generation_trace.completion_tokens,
            "total_tokens": generation_trace.total_tokens,
            "estimated_cost_usd": generation_trace.estimated_cost_usd,
            "token_usage_source": generation_trace.token_usage_source,
            "error": "",
        },
        "grounding": {
            "retrieval_outcome": retrieval.to_dict(),
            "answer_context": answer_context.to_dict(),
            "route_resolution": route_resolution.to_dict(),
            "evidence_documents": [evidence_document.to_dict()],
        },
        "diagnostics": {
            "analysis": analysis.to_dict(),
            "diagnostics": diagnostics.to_dict(),
        },
        "traces": {
            "route_trace": route_trace.to_dict(),
            "graph_trace": graph_trace.to_dict(),
            "generation_trace": generation_trace.to_dict(),
            "trace_event": trace_event.to_dict(),
        },
    }


def _payload_without_new_summary_fields(question: str) -> dict:
    payload = _answer_payload(question)
    for field_name in (
        "prompt_tokens",
        "completion_tokens",
        "total_tokens",
        "estimated_cost_usd",
        "token_usage_source",
    ):
        payload["summary"].pop(field_name)
    return payload


class _DummyAnswerResponse:
    def __init__(self, question: str, explain_routing: bool, stream: bool) -> None:
        self.question = question
        self.explain_routing = explain_routing
        self.stream = stream

    def to_dict(self) -> dict:
        return _answer_payload(self.question, stream=self.stream)


class _FakeApiSystem:
    def __init__(self) -> None:
        self.config = _API_CONFIG
        self.system_ready = False
        self.build_initialized = False
        self.serving_initialized = False
        self.initialize_build_calls = 0
        self.initialize_serving_calls = 0
        self.build_calls = 0
        self.rebuild_calls = 0
        self.answer_calls: list[tuple[str, bool, bool]] = []
        self.close_calls = 0

    def is_build_initialized(self) -> bool:
        return self.build_initialized

    def is_serving_initialized(self) -> bool:
        return self.serving_initialized

    def initialize_build_runtime(self, progress=None, *, neo4j_manager=None):
        del progress, neo4j_manager
        self.initialize_build_calls += 1
        self.build_initialized = True
        return None

    def initialize_serving_runtime(self, progress=None, *, query_tracer=None, neo4j_manager=None):
        del progress, query_tracer, neo4j_manager
        self.initialize_serving_calls += 1
        self.serving_initialized = True
        return None

    def build_knowledge_base(self, progress=None) -> None:
        del progress
        self.build_calls += 1
        self.system_ready = True

    def rebuild_knowledge_base(self, progress=None) -> None:
        del progress
        self.rebuild_calls += 1
        self.system_ready = True

    def collect_system_stats(self) -> dict:
        return {
            "ready": self.system_ready,
            "artifact_manifest": {
                "health": ARTIFACT_HEALTH_READY if self.system_ready else ARTIFACT_HEALTH_MISSING,
            },
        }

    def collect_startup_diagnostics(self, mode: str) -> StartupDiagnostics:
        return _diagnostics(
            mode=mode,
            system_ready=self.system_ready,
            build_initialized=self.build_initialized,
            serving_initialized=self.serving_initialized,
        )

    def answer_question_response(
        self,
        question: str,
        *,
        stream: bool = False,
        explain_routing: bool = False,
        message_callback=None,
        chunk_callback=None,
    ):
        if stream:
            if message_callback:
                message_callback("Running query routing...")
            if chunk_callback:
                chunk_callback("chunk-1")
                chunk_callback("chunk-2")
        self.answer_calls.append((question, stream, explain_routing))
        return _DummyAnswerResponse(question, explain_routing, stream)

    def close(self) -> None:
        self.close_calls += 1


class _BlockingApiSystem(_FakeApiSystem):
    def __init__(self) -> None:
        super().__init__()
        self.system_ready = True
        self.serving_initialized = True
        self.answer_started = threading.Event()
        self.release_answer = threading.Event()

    def answer_question_response(
        self,
        question: str,
        *,
        stream: bool = False,
        explain_routing: bool = False,
        message_callback=None,
        chunk_callback=None,
    ):
        del message_callback, chunk_callback
        self.answer_calls.append((question, stream, explain_routing))
        self.answer_started.set()
        self.release_answer.wait(timeout=2.0)
        return _DummyAnswerResponse(question, explain_routing, stream)


class _ConcurrentAnswerApiSystem(_FakeApiSystem):
    def __init__(self) -> None:
        super().__init__()
        self.system_ready = True
        self.serving_initialized = True
        self._state_lock = threading.Lock()
        self.started_answers = 0
        self.both_answers_started = threading.Event()
        self.release_answers = threading.Event()

    def answer_question_response(
        self,
        question: str,
        *,
        stream: bool = False,
        explain_routing: bool = False,
        message_callback=None,
        chunk_callback=None,
    ):
        del message_callback, chunk_callback
        self.answer_calls.append((question, stream, explain_routing))
        with self._state_lock:
            self.started_answers += 1
            if self.started_answers >= 2:
                self.both_answers_started.set()
        self.release_answers.wait(timeout=2.0)
        return _DummyAnswerResponse(question, explain_routing, stream)


class _BlockingBuildApiSystem(_FakeApiSystem):
    def __init__(self) -> None:
        super().__init__()
        self.build_initialized = True
        self.build_started = threading.Event()
        self.release_build = threading.Event()

    def build_knowledge_base(self, progress=None) -> None:
        del progress
        self.build_calls += 1
        self.build_started.set()
        self.release_build.wait(timeout=2.0)
        self.system_ready = True


class _ChunkFloodApiSystem(_FakeApiSystem):
    def __init__(self) -> None:
        super().__init__()
        self.system_ready = True
        self.serving_initialized = True
        self.answer_finished = threading.Event()

    def answer_question_response(
        self,
        question: str,
        *,
        stream: bool = False,
        explain_routing: bool = False,
        message_callback=None,
        chunk_callback=None,
    ):
        try:
            if stream:
                if message_callback:
                    message_callback("Running query routing...")
                if chunk_callback:
                    for index in range(512):
                        chunk_callback(f"chunk-{index}")
            self.answer_calls.append((question, stream, explain_routing))
            return _DummyAnswerResponse(question, explain_routing, stream)
        finally:
            self.answer_finished.set()


class ApiAppTests(unittest.TestCase):
    def test_api_service_canonical_and_compat_imports_match(self) -> None:
        from rag_modules.interfaces.api import service as compat_service
        from rag_modules.interfaces.api.services import (
            BuildJobConflictError as CanonicalBuildJobConflictError,
        )
        from rag_modules.interfaces.api.services import (
            BuildJobNotFoundError as CanonicalBuildJobNotFoundError,
        )
        from rag_modules.interfaces.api.services import (
            GraphRAGBuildApiService as CanonicalBuildService,
        )
        from rag_modules.interfaces.api.services import (
            GraphRAGServingApiService as CanonicalServingService,
        )
        from rag_modules.interfaces.api.services import (
            SystemNotReadyError as CanonicalSystemNotReadyError,
        )

        self.assertIs(compat_service.GraphRAGBuildApiService, CanonicalBuildService)
        self.assertIs(compat_service.GraphRAGServingApiService, CanonicalServingService)
        self.assertIs(compat_service.SystemNotReadyError, CanonicalSystemNotReadyError)
        self.assertIs(compat_service.BuildJobNotFoundError, CanonicalBuildJobNotFoundError)
        self.assertIs(compat_service.BuildJobConflictError, CanonicalBuildJobConflictError)

    def test_serving_liveness_is_public_and_does_not_require_readiness(self) -> None:
        app = create_serving_api_app(system=_FakeApiSystem())

        with TestClient(app) as client:
            response = client.get("/health/live")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ok")
        self.assertFalse(response.json()["system_ready"])

    def test_serving_readiness_returns_503_until_system_is_ready(self) -> None:
        system = _FakeApiSystem()
        app = create_serving_api_app(system=system)

        with TestClient(app) as client:
            unready_response = client.get("/health/ready")
            system.system_ready = True
            system.serving_initialized = True
            ready_response = client.get("/health/ready")

        self.assertEqual(unready_response.status_code, 503)
        self.assertEqual(unready_response.json()["status"], "not_ready")
        self.assertEqual(ready_response.status_code, 200)
        self.assertEqual(ready_response.json()["status"], "ok")

    def test_build_readiness_requires_initialized_build_runtime(self) -> None:
        system = _FakeApiSystem()
        app = create_build_api_app(system=system)

        with TestClient(app) as client:
            unready_response = client.get("/health/ready")
            system.build_initialized = True
            ready_response = client.get("/health/ready")

        self.assertEqual(unready_response.status_code, 503)
        self.assertEqual(ready_response.status_code, 200)

    def test_serving_health_surface_reports_runtime_state(self) -> None:
        app = create_serving_api_app(system=_FakeApiSystem())

        with _client(app) as client:
            response = client.get("/health")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "ok")
        self.assertFalse(payload["system_ready"])
        self.assertEqual(payload["manifest_health"], ARTIFACT_HEALTH_MISSING)

    def test_build_health_surface_reports_runtime_state(self) -> None:
        app = create_build_api_app(system=_FakeApiSystem())

        with _client(app) as client:
            response = client.get("/health")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "ok")
        self.assertFalse(payload["build_initialized"])
        self.assertEqual(payload["manifest_health"], ARTIFACT_HEALTH_MISSING)

    def test_serving_stats_and_diagnostics_use_structured_response_models(self) -> None:
        system = _FakeApiSystem()
        system.system_ready = True
        system.serving_initialized = True
        app = create_serving_api_app(system=system)

        with _client(app) as client:
            stats_response = client.get("/stats")
            diagnostics_response = client.get("/diagnostics")

        self.assertEqual(stats_response.status_code, 200)
        stats_payload = stats_response.json()["stats"]
        self.assertTrue(stats_payload["ready"])
        self.assertIn("models", stats_payload)
        self.assertIn("trace_stats", stats_payload)
        self.assertIn("route_stats", stats_payload)
        self.assertIn("artifact_manifest", stats_payload)
        self.assertEqual(
            stats_payload["artifact_manifest"]["health"],
            ARTIFACT_HEALTH_READY,
        )

        self.assertEqual(diagnostics_response.status_code, 200)
        diagnostics_payload = diagnostics_response.json()["diagnostics"]
        self.assertEqual(diagnostics_payload["mode"], "serve")
        self.assertTrue(diagnostics_payload["system_ready"])
        self.assertTrue(diagnostics_payload["retrieval_engines_initialized"])
        self.assertIn("trace_stats", diagnostics_payload)
        self.assertEqual(
            diagnostics_payload["manifest"]["collection_name"],
            "recipes",
        )

    def test_serving_answer_returns_409_when_artifacts_are_not_ready(self) -> None:
        system = _FakeApiSystem()
        app = create_serving_api_app(system=system)

        with _client(app) as client:
            response = client.post("/answers", json={"question": "Can I cook tofu?"})

        self.assertEqual(response.status_code, 409)
        payload = response.json()
        self.assertFalse(payload["ok"])
        self.assertIn("Build the knowledge base first", payload["message"])
        self.assertEqual(system.initialize_serving_calls, 1)

    def test_serving_surface_does_not_expose_build_routes(self) -> None:
        app = create_serving_api_app(system=_FakeApiSystem())

        with _client(app) as client:
            response = client.post("/knowledge-base/build")

        self.assertEqual(response.status_code, 404)

    def test_build_surface_does_not_expose_answer_routes(self) -> None:
        app = create_build_api_app(system=_FakeApiSystem())

        with _client(app) as client:
            response = client.post("/answers", json={"question": "Can I cook tofu?"})

        self.assertEqual(response.status_code, 404)

    def test_build_flow_uses_build_api_surface(self) -> None:
        system = _FakeApiSystem()
        app = create_build_api_app(system=system)

        with _client(app) as client:
            build_response = client.post("/knowledge-base/build")
            job_payload = build_response.json()["job"]
            finished_job = _wait_for_job_status(
                client,
                job_payload["job_id"],
                "succeeded",
            )

        self.assertEqual(build_response.status_code, 202)
        self.assertEqual(system.initialize_build_calls, 1)
        self.assertEqual(system.build_calls, 1)
        self.assertEqual(system.initialize_serving_calls, 0)
        self.assertEqual(finished_job["job_type"], "build")
        self.assertEqual(finished_job["result"]["message"], "Knowledge base build completed.")

    def test_build_jobs_surface_lists_and_reads_jobs(self) -> None:
        system = _FakeApiSystem()
        app = create_build_api_app(system=system)

        with _client(app) as client:
            build_response = client.post("/jobs/build")
            build_job = build_response.json()["job"]
            finished_job = _wait_for_job_status(client, build_job["job_id"], "succeeded")
            list_response = client.get("/jobs")
            detail_response = client.get(f"/jobs/{build_job['job_id']}")

        self.assertEqual(build_response.status_code, 202)
        self.assertEqual(list_response.status_code, 200)
        self.assertEqual(detail_response.status_code, 200)
        self.assertEqual(detail_response.json()["job"]["job_id"], build_job["job_id"])
        self.assertEqual(detail_response.json()["job"]["status"], "succeeded")
        self.assertEqual(list_response.json()["jobs"][0]["job_id"], build_job["job_id"])
        self.assertEqual(finished_job["result"]["message"], "Knowledge base build completed.")

    def test_build_jobs_surface_rejects_parallel_build_submission(self) -> None:
        system = _BlockingBuildApiSystem()
        app = create_build_api_app(system=system)

        with _client(app) as client:
            first_response = client.post("/jobs/build")
            first_job = first_response.json()["job"]
            self.assertTrue(system.build_started.wait(timeout=1.0))

            conflict_response = client.post("/jobs/rebuild")

            system.release_build.set()
            _wait_for_job_status(client, first_job["job_id"], "succeeded")

        self.assertEqual(first_response.status_code, 202)
        self.assertEqual(conflict_response.status_code, 409)
        conflict_payload = conflict_response.json()
        self.assertFalse(conflict_payload["ok"])
        self.assertEqual(conflict_payload["job"]["job_id"], first_job["job_id"])

    def test_answer_flow_uses_serving_api_surface(self) -> None:
        system = _FakeApiSystem()
        system.system_ready = True
        app = create_serving_api_app(system=system)

        with _client(app) as client:
            answer_response = client.post(
                "/answers",
                json={
                    "question": "Can I cook tofu?",
                    "stream": False,
                    "explain_routing": True,
                },
            )

        self.assertEqual(answer_response.status_code, 200)
        self.assertEqual(system.initialize_build_calls, 0)
        self.assertEqual(system.initialize_serving_calls, 1)
        self.assertEqual(system.answer_calls, [("Can I cook tofu?", False, True)])
        answer_payload = answer_response.json()["response"]
        self.assertEqual(answer_payload["summary"]["answer"], "answer:Can I cook tofu?")
        self.assertEqual(
            answer_payload["diagnostics"]["diagnostics"]["overall_bucket"],
            "ok",
        )
        self.assertEqual(answer_payload["summary"]["prompt_tokens"], 11)
        self.assertEqual(answer_payload["summary"]["total_tokens"], 18)

    def test_answer_response_model_accepts_runtime_shaped_payload(self) -> None:
        payload = _answer_payload("Can I cook tofu?")

        model = AnswerResponseModel.model_validate({"response": payload})

        dumped = model.model_dump()
        self.assertEqual(dumped["response"]["summary"]["answer"], "answer:Can I cook tofu?")
        self.assertEqual(dumped["response"]["summary"]["prompt_tokens"], 11)
        self.assertEqual(
            dumped["response"]["grounding"]["retrieval_outcome"]["evidence_documents"][0][
                "recipe_name"
            ],
            "mapo tofu",
        )
        self.assertEqual(
            dumped["response"]["diagnostics"]["diagnostics"]["overall_bucket"],
            "ok",
        )
        self.assertEqual(
            dumped["response"]["traces"]["generation_trace"]["token_usage_source"],
            "test",
        )

    def test_answer_response_model_rejects_unknown_stable_fields(self) -> None:
        accepted_locations: list[tuple[str, ...]] = []

        def check_rejects_extra_field(payload: dict, expected_location: tuple[str, ...]) -> None:
            try:
                AnswerResponseModel.model_validate({"response": payload})
            except ValidationError as exc:
                self.assertIn(
                    expected_location,
                    {tuple(error["loc"]) for error in exc.errors()},
                )
            else:
                accepted_locations.append(expected_location)

        payload = _payload_without_new_summary_fields("Can I cook tofu?")
        payload["summary"]["unexpected"] = True

        check_rejects_extra_field(payload, ("response", "summary", "unexpected"))

        payload = _payload_without_new_summary_fields("Can I cook tofu?")
        payload["traces"]["generation_trace"]["unexpected"] = True

        check_rejects_extra_field(payload, ("response", "traces", "generation_trace", "unexpected"))

        payload = _payload_without_new_summary_fields("Can I cook tofu?")
        payload["diagnostics"]["diagnostics"]["explained"] = True

        check_rejects_extra_field(payload, ("response", "diagnostics", "diagnostics", "explained"))
        self.assertEqual([], accepted_locations)

    def test_answer_response_schema_exposes_summary_token_fields(self) -> None:
        app = create_serving_api_app(system=_FakeApiSystem())

        with _client(app) as client:
            schema = client.get("/openapi.json").json()

        summary_schema = schema["components"]["schemas"]["AnswerSummaryModel"]
        self.assertIn("prompt_tokens", summary_schema["properties"])
        self.assertIn("completion_tokens", summary_schema["properties"])
        self.assertIn("total_tokens", summary_schema["properties"])
        self.assertIn("estimated_cost_usd", summary_schema["properties"])
        self.assertIn("token_usage_source", summary_schema["properties"])

    def test_answer_stream_uses_sse_surface(self) -> None:
        system = _FakeApiSystem()
        system.system_ready = True
        app = create_serving_api_app(system=system)

        with _client(app) as client:
            with client.stream(
                "POST",
                "/answers",
                json={
                    "question": "Can I cook tofu?",
                    "stream": True,
                    "explain_routing": True,
                },
            ) as answer_response:
                body = "".join(answer_response.iter_text())

        self.assertEqual(answer_response.status_code, 200)
        self.assertTrue(answer_response.headers["content-type"].startswith("text/event-stream"))
        self.assertEqual(system.initialize_build_calls, 0)
        self.assertEqual(system.initialize_serving_calls, 1)
        self.assertEqual(system.answer_calls, [("Can I cook tofu?", True, True)])

        events: dict[str, list[dict]] = {}
        for block in body.strip().split("\n\n"):
            lines = [line for line in block.splitlines() if line]
            event_name = ""
            data = None
            for line in lines:
                if line.startswith("event: "):
                    event_name = line[len("event: ") :]
                elif line.startswith("data: "):
                    data = json.loads(line[len("data: ") :])
            if event_name:
                events.setdefault(event_name, []).append(data)

        self.assertEqual(events["message"][0]["message"], "Running query routing...")
        self.assertEqual(events["chunk"][0]["content"], "chunk-1")
        self.assertEqual(events["chunk"][1]["content"], "chunk-2")
        self.assertEqual(
            events["result"][0]["response"]["summary"]["answer"],
            "answer:Can I cook tofu?",
        )
        self.assertEqual(events["done"][0]["ok"], True)

    def test_explicit_answer_stream_route_uses_sse_surface(self) -> None:
        system = _FakeApiSystem()
        system.system_ready = True
        app = create_serving_api_app(system=system)

        with _client(app) as client:
            with client.stream(
                "POST",
                "/answers/stream",
                json={
                    "question": "Explain mapo tofu",
                    "explain_routing": False,
                },
            ) as answer_response:
                body = "".join(answer_response.iter_text())

            openapi_response = client.get("/openapi.json")

        self.assertEqual(answer_response.status_code, 200)
        self.assertTrue(answer_response.headers["content-type"].startswith("text/event-stream"))
        self.assertEqual(system.answer_calls, [("Explain mapo tofu", True, False)])
        self.assertIn("event: result", body)

        schema = openapi_response.json()
        self.assertIn("/answers/stream", schema["paths"])
        stream_post = schema["paths"]["/answers/stream"]["post"]
        self.assertEqual(
            stream_post["responses"]["200"]["content"].keys(),
            {"text/event-stream"},
        )

    def test_serving_stats_do_not_block_while_answer_is_in_flight(self) -> None:
        system = _BlockingApiSystem()
        service = GraphRAGServingApiService(system=system)
        answer_done = threading.Event()
        stats_done = threading.Event()

        def run_answer() -> None:
            try:
                service.answer_question(question="slow tofu")
            finally:
                answer_done.set()

        def run_stats() -> None:
            service.collect_stats()
            stats_done.set()

        answer_thread = threading.Thread(target=run_answer)
        stats_thread = threading.Thread(target=run_stats)
        answer_thread.start()
        self.assertTrue(system.answer_started.wait(timeout=1.0))

        stats_thread.start()
        self.assertTrue(
            stats_done.wait(timeout=0.5),
            "stats collection should not wait for the in-flight answer lock",
        )
        self.assertFalse(answer_done.is_set())

        system.release_answer.set()
        answer_thread.join(timeout=1.0)
        stats_thread.join(timeout=1.0)
        self.assertTrue(answer_done.is_set())

    def test_serving_answers_can_run_concurrently(self) -> None:
        system = _ConcurrentAnswerApiSystem()
        service = GraphRAGServingApiService(system=system)
        first_done = threading.Event()
        second_done = threading.Event()

        def run_first() -> None:
            try:
                service.answer_question(question="first tofu")
            finally:
                first_done.set()

        def run_second() -> None:
            try:
                service.answer_question(question="second tofu")
            finally:
                second_done.set()

        first_thread = threading.Thread(target=run_first)
        second_thread = threading.Thread(target=run_second)
        first_thread.start()
        second_thread.start()

        self.assertTrue(
            system.both_answers_started.wait(timeout=0.5),
            "independent answer requests should not serialize behind a global answer lock",
        )
        self.assertFalse(first_done.is_set())
        self.assertFalse(second_done.is_set())

        system.release_answers.set()
        first_thread.join(timeout=1.0)
        second_thread.join(timeout=1.0)
        self.assertTrue(first_done.is_set())
        self.assertTrue(second_done.is_set())
        self.assertEqual(len(system.answer_calls), 2)

    def test_serving_service_uses_configured_stream_limits(self) -> None:
        system = _FakeApiSystem()
        config = build_test_config(
            {
                "api": {
                    "access_token": _API_TOKEN,
                    "stream_executor_max_workers": 2,
                    "stream_queue_max_size": 7,
                }
            }
        )
        service = GraphRAGServingApiService(system=system, config=config)

        self.assertEqual(service._stream_executor_max_workers, 2)
        self.assertEqual(service._stream_queue_max_size, 7)

    def test_serving_answers_return_429_when_admission_limit_is_full(self) -> None:
        system = _BlockingApiSystem()
        config = build_test_config(
            {
                "api": {
                    "access_token": _API_TOKEN,
                    "max_concurrent_answers": 1,
                    "answer_acquire_timeout_seconds": 0.01,
                }
            }
        )
        app = create_serving_api_app(system=system, config=config)

        with _client(app) as client:
            service = app.state.api_service
            first_done = threading.Event()

            def run_first() -> None:
                try:
                    service.answer_question(question="first tofu")
                finally:
                    first_done.set()

            first_thread = threading.Thread(target=run_first)
            first_thread.start()
            self.assertTrue(system.answer_started.wait(timeout=1.0))

            response = client.post(
                "/answers",
                json={
                    "question": "second tofu",
                    "stream": False,
                    "explain_routing": True,
                },
            )

            system.release_answer.set()
            first_thread.join(timeout=1.0)
            self.assertTrue(first_done.is_set())

        self.assertEqual(response.status_code, 429)
        payload = response.json()
        self.assertEqual(payload["error_type"], "api_backpressure")
        self.assertEqual(
            payload["message"],
            "Serving answer concurrency limit exceeded.",
        )

    def test_serving_streams_emit_error_events_when_admission_limit_is_full(self) -> None:
        system = _BlockingApiSystem()
        config = build_test_config(
            {
                "api": {
                    "access_token": _API_TOKEN,
                    "max_concurrent_answers": 1,
                    "answer_acquire_timeout_seconds": 0.01,
                    "stream_executor_max_workers": 2,
                    "stream_queue_max_size": 4,
                }
            }
        )
        app = create_serving_api_app(system=system, config=config)

        with _client(app) as client:
            service = app.state.api_service
            first_done = threading.Event()

            def run_first() -> None:
                try:
                    service.answer_question(question="busy tofu")
                finally:
                    first_done.set()

            first_thread = threading.Thread(target=run_first)
            first_thread.start()
            self.assertTrue(system.answer_started.wait(timeout=1.0))

            with client.stream(
                "POST",
                "/answers/stream",
                json={
                    "question": "blocked tofu",
                    "explain_routing": True,
                },
            ) as response:
                body = "".join(response.iter_text())

            system.release_answer.set()
            first_thread.join(timeout=1.0)
            self.assertTrue(first_done.is_set())

        self.assertEqual(response.status_code, 200)
        self.assertIn("event: error", body)
        self.assertIn('"error_type": "api_backpressure"', body)
        self.assertIn("event: done", body)

    def test_build_diagnostics_use_cached_snapshot_while_build_is_in_flight(self) -> None:
        system = _BlockingBuildApiSystem()
        service = GraphRAGBuildApiService(system=system)
        service.collect_stats()
        baseline = service.collect_startup_diagnostics("build")
        diagnostics_done = threading.Event()
        diagnostics_payload: dict[str, object] = {}

        job = service.submit_build_job(rebuild=False)
        self.assertTrue(system.build_started.wait(timeout=1.0))

        def read_diagnostics() -> None:
            diagnostics_payload["diagnostics"] = service.collect_startup_diagnostics("build")
            diagnostics_payload["stats"] = service.collect_stats()
            diagnostics_done.set()

        diagnostics_thread = threading.Thread(target=read_diagnostics)
        diagnostics_thread.start()
        self.assertTrue(
            diagnostics_done.wait(timeout=0.5),
            "diagnostics and stats should return cached snapshots during a build",
        )
        self.assertEqual(diagnostics_payload["diagnostics"], baseline)
        self.assertEqual(diagnostics_payload["stats"]["ready"], False)

        system.release_build.set()
        diagnostics_thread.join(timeout=1.0)
        completed_job = _wait_for_service_job_status(
            service,
            job["job_id"],
            "succeeded",
        )
        self.assertEqual(completed_job["status"], "succeeded")

    def test_closing_stream_consumer_stops_background_answer_runner(self) -> None:
        system = _ChunkFloodApiSystem()
        service = GraphRAGServingApiService(system=system)
        events = service.stream_answer_question_events(question="flooded tofu")

        first_event = next(events)
        self.assertEqual(first_event.event, AnswerStreamEventType.message)

        events.close()

        self.assertTrue(
            system.answer_finished.wait(timeout=1.0),
            "closing the SSE consumer should let the background stream runner exit",
        )

    def test_stream_answer_service_emits_typed_events(self) -> None:
        system = _FakeApiSystem()
        system.system_ready = True
        system.serving_initialized = True
        service = GraphRAGServingApiService(system=system)

        events = list(
            service.stream_answer_question_events(
                question="Typed stream",
                explain_routing=True,
            )
        )

        self.assertEqual(
            [event.event for event in events],
            [
                AnswerStreamEventType.message,
                AnswerStreamEventType.chunk,
                AnswerStreamEventType.chunk,
                AnswerStreamEventType.result,
                AnswerStreamEventType.done,
            ],
        )
        self.assertEqual(events[0].data.message, "Running query routing...")
        self.assertEqual(events[1].data.content, "chunk-1")
        self.assertEqual(events[3].data.response.summary.answer, "answer:Typed stream")
        self.assertTrue(events[4].data.ok)

    def test_protected_routes_require_api_credentials(self) -> None:
        app = create_serving_api_app(system=_FakeApiSystem())

        with TestClient(app) as client:
            health_response = client.get("/health")
            unauthorized_response = client.get("/stats")
            invalid_response = client.get(
                "/stats",
                headers={"Authorization": "Bearer wrong-token"},
            )
            api_key_response = client.get(
                "/stats",
                headers={"X-API-Key": _API_TOKEN},
            )

        self.assertEqual(health_response.status_code, 200)
        self.assertEqual(unauthorized_response.status_code, 401)
        self.assertEqual(invalid_response.status_code, 401)
        self.assertEqual(
            unauthorized_response.headers["www-authenticate"],
            "Bearer",
        )
        self.assertEqual(api_key_response.status_code, 200)

    def test_authentication_fails_closed_when_token_is_not_configured(self) -> None:
        config = build_test_config({"api": {"auth_enabled": True, "access_token": ""}})
        app = create_serving_api_app(system=_FakeApiSystem(), config=config)

        with TestClient(app) as client:
            response = client.get("/stats")

        self.assertEqual(response.status_code, 503)
        self.assertIn("no access token", response.json()["message"])

    def test_authentication_rejects_weak_configured_token(self) -> None:
        config = build_test_config({"api": {"auth_enabled": True, "access_token": "too-short"}})
        app = create_serving_api_app(system=_FakeApiSystem(), config=config)

        with TestClient(app) as client:
            response = client.get(
                "/stats",
                headers={"Authorization": "Bearer too-short"},
            )

        self.assertEqual(response.status_code, 503)
        self.assertIn("at least 16 characters", response.json()["message"])

    def test_request_body_and_question_limits_are_enforced(self) -> None:
        system = _FakeApiSystem()
        system.system_ready = True
        body_limited_config = build_test_config(
            {
                "api": {
                    "access_token": _API_TOKEN,
                    "max_request_body_bytes": 1024,
                }
            }
        )
        body_limited_app = create_serving_api_app(
            system=system,
            config=body_limited_config,
        )
        field_limited_app = create_serving_api_app(system=_FakeApiSystem())

        with _client(body_limited_app) as client:
            oversized_body = client.post(
                "/answers",
                json={"question": "x" * 2000},
            )
        with _client(field_limited_app) as client:
            oversized_question = client.post(
                "/answers",
                json={"question": "x" * (MAX_QUESTION_CHARS + 1)},
            )
            blank_question = client.post(
                "/answers",
                json={"question": "   "},
            )

        self.assertEqual(oversized_body.status_code, 413)
        self.assertEqual(oversized_question.status_code, 422)
        self.assertEqual(blank_question.status_code, 422)

    def test_prometheus_metrics_endpoint_is_public(self) -> None:
        app = create_serving_api_app(system=_FakeApiSystem(), config=_API_CONFIG)

        with TestClient(app) as client:
            response = client.get("/metrics")

        self.assertEqual(response.status_code, 200)
        self.assertIn("graphrag_queries_total", response.text)
        self.assertTrue(response.headers["content-type"].startswith("text/plain"))


if __name__ == "__main__":
    unittest.main()

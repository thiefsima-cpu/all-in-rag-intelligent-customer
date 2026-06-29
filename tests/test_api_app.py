from __future__ import annotations

import json
import re
import tempfile
import threading
import time
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from pydantic import ValidationError

from rag_modules.app.diagnostics import ArtifactManifestDiagnostics, StartupDiagnostics
from rag_modules.app.services.answer_models import QuestionAnswerResponse, QuestionAnswerResult
from rag_modules.configuration.testing import build_test_config
from rag_modules.contracts import EvidenceDocument
from rag_modules.interfaces.api import create_build_api_app, create_serving_api_app
from rag_modules.interfaces.api.answer_models import (
    MAX_QUESTION_CHARS,
    AnswerResponseModel,
    AnswerStreamEventType,
)
from rag_modules.interfaces.api.error_models import ErrorCode, build_error_payload
from rag_modules.interfaces.api.services import (
    GraphRAGBuildApiService,
    GraphRAGServingApiService,
)
from rag_modules.interfaces.api.versioning import API_VERSION
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
from rag_modules.runtime.artifacts import ARTIFACT_HEALTH_MISSING, ARTIFACT_HEALTH_READY

_API_TOKEN = "test-api-access-token"
_API_CONFIG = build_test_config({"api": {"access_token": _API_TOKEN}})


def _client(app: object) -> TestClient:
    return TestClient(
        app,
        headers={"Authorization": f"Bearer {_API_TOKEN}"},
    )


def _assert_error_response(
    response,
    *,
    status_code: int,
    code: str,
    request_id: str | None = None,
) -> dict:
    assert response.status_code == status_code
    payload = response.json()
    assert payload["ok"] is False
    assert payload["error"]["code"] == code
    assert "message" in payload["error"]
    assert "message" not in {key for key in payload if key != "error"}
    assert "error_type" not in payload
    assert payload["request_id"] == response.headers["x-request-id"]
    if request_id is not None:
        assert payload["request_id"] == request_id
    return payload


def _assert_request_id(value: str) -> None:
    assert re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", value)


def _parse_sse_events(body: str) -> dict[str, list[dict]]:
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
    return events


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


def _observe_lifecycle_requests(service: GraphRAGServingApiService) -> threading.Event:
    lifecycle_requested = threading.Event()
    original_lifecycle_operation = service._locks.lifecycle_operation

    @contextmanager
    def observed_lifecycle_operation():
        lifecycle_requested.set()
        with original_lifecycle_operation():
            yield

    service._locks.lifecycle_operation = observed_lifecycle_operation
    return lifecycle_requested


def _serving_race_config(**api_overrides: object):
    api_settings = {
        "access_token": _API_TOKEN,
        "serving_hot_refresh_enabled": False,
    }
    api_settings.update(api_overrides)
    return build_test_config({"api": api_settings})


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


def _answer_result(question: str, *, stream: bool = False) -> QuestionAnswerResult:
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

    return QuestionAnswerResult(
        answer=f"answer:{question}",
        analysis=analysis,
        retrieval_outcome=retrieval,
        answer_context=answer_context,
        route_resolution=route_resolution,
        latency_ms=12.3,
        route_trace=route_trace,
        graph_trace=graph_trace,
        generation_trace=generation_trace,
        trace_event=trace_event,
    )


def _answer_response(question: str, *, stream: bool = False) -> QuestionAnswerResponse:
    return _answer_result(question, stream=stream).to_response()


def _answer_payload(question: str, *, stream: bool = False) -> dict:
    return _answer_response(question, stream=stream).to_dict()


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
        self._response = _answer_response(question, stream=stream)

    def __getattr__(self, name: str):
        return getattr(self._response, name)

    def to_dict(self) -> dict:
        return self._response.to_dict()


class _FailedAnswerResponse(_DummyAnswerResponse):
    def __init__(self, question: str, secret: str, stream: bool) -> None:
        super().__init__(question, False, stream)
        self.secret = secret
        self._response.summary.status = "failed"
        self._response.summary.answer = f"raw failure: {self.secret}"
        self._response.summary.error = self.secret
        self._response.traces.route_trace.error = self.secret

    def to_dict(self) -> dict:
        return self._response.to_dict()


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


class _FailedAnswerSystem(_FakeApiSystem):
    def __init__(self, secret: str) -> None:
        super().__init__()
        self.system_ready = True
        self.serving_initialized = True
        self.secret = secret

    def answer_question_response(self, question: str, *, stream=False, **kwargs):
        del kwargs
        return _FailedAnswerResponse(question, self.secret, stream)


class _PublicManifestErrorSystem(_FakeApiSystem):
    def __init__(self, secret: str) -> None:
        super().__init__()
        self.secret = secret

    def collect_startup_diagnostics(self, mode: str) -> StartupDiagnostics:
        diagnostics = super().collect_startup_diagnostics(mode)
        diagnostics.manifest.last_error = self.secret
        return diagnostics

    def collect_system_stats(self) -> dict:
        payload = super().collect_system_stats()
        payload["artifact_manifest"]["last_error"] = self.secret
        return payload


class _ErrorTraceAnswerResponse(_DummyAnswerResponse):
    def __init__(self, question: str, secret: str) -> None:
        super().__init__(question, False, False)
        self.secret = secret
        self._response.summary.error = self.secret
        self._response.traces.route_trace.error = self.secret
        self._response.traces.graph_trace.error = self.secret
        self._response.traces.trace_event.error = self.secret

    def to_dict(self) -> dict:
        return self._response.to_dict()


class _PublicAnswerErrorSystem(_FakeApiSystem):
    def __init__(self, secret: str) -> None:
        super().__init__()
        self.system_ready = True
        self.serving_initialized = True
        self.secret = secret

    def answer_question_response(self, question: str, **kwargs):
        del kwargs
        return _ErrorTraceAnswerResponse(question, self.secret)


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


class _FailingBuildApiSystem(_FakeApiSystem):
    def __init__(self, secret: str) -> None:
        super().__init__()
        self.build_initialized = True
        self.secret = secret

    def build_knowledge_base(self, progress=None) -> None:
        if progress:
            progress(f"private progress {self.secret}")
        raise RuntimeError(self.secret)


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


class _LifecycleRaceApiSystem(_FakeApiSystem):
    def __init__(self) -> None:
        super().__init__()
        self.system_ready = True
        self.serving_initialized = True
        self.first_answer_started = threading.Event()
        self.second_answer_started = threading.Event()
        self.release_answers = threading.Event()
        self.refresh_started = threading.Event()
        self.close_started = threading.Event()
        self.refresh_calls = 0

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
        if question == "first tofu":
            self.first_answer_started.set()
        if question == "second tofu":
            self.second_answer_started.set()
        self.release_answers.wait(timeout=2.0)
        return _DummyAnswerResponse(question, explain_routing, stream)

    def refresh_serving_runtime(self, progress=None, *, force: bool = True):
        del progress, force
        self.refresh_calls += 1
        self.refresh_started.set()

    def close(self) -> None:
        super().close()
        self.system_ready = False
        self.serving_initialized = False
        self.close_started.set()


class _BlockingStreamApiSystem(_FakeApiSystem):
    def __init__(self) -> None:
        super().__init__()
        self.system_ready = True
        self.serving_initialized = True
        self.first_stream_started = threading.Event()
        self.second_stream_started = threading.Event()
        self.release_streams = threading.Event()

    def answer_question_response(
        self,
        question: str,
        *,
        stream: bool = False,
        explain_routing: bool = False,
        message_callback=None,
        chunk_callback=None,
    ):
        del chunk_callback
        if question == "first stream":
            self.first_stream_started.set()
        if question == "second stream":
            self.second_stream_started.set()
        if stream and message_callback:
            message_callback(f"stream-started:{question}")
        self.release_streams.wait(timeout=2.0)
        self.answer_calls.append((question, stream, explain_routing))
        return _DummyAnswerResponse(question, explain_routing, stream)

    def close(self) -> None:
        super().close()
        self.system_ready = False
        self.serving_initialized = False


class ApiAppTests(unittest.TestCase):
    def test_error_catalog_builds_the_new_breaking_contract(self) -> None:
        payload = build_error_payload(
            ErrorCode.VALIDATION_ERROR,
            request_id="catalog-test",
            details=[{"field": "body.question", "reason": "string_too_long"}],
        )

        self.assertEqual(
            payload,
            {
                "ok": False,
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": "The request is invalid.",
                    "details": [{"field": "body.question", "reason": "string_too_long"}],
                },
                "request_id": "catalog-test",
            },
        )

    def test_valid_client_request_id_is_preserved_on_success(self) -> None:
        app = create_serving_api_app(system=_FakeApiSystem())

        with TestClient(app) as client:
            response = client.get("/health", headers={"X-Request-ID": "client.req:42"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["x-request-id"], "client.req:42")

    def test_missing_or_invalid_request_id_is_replaced(self) -> None:
        app = create_serving_api_app(system=_FakeApiSystem())

        with TestClient(app) as client:
            missing = client.get("/health")
            invalid = client.get("/health", headers={"X-Request-ID": "bad/id secret"})

        _assert_request_id(missing.headers["x-request-id"])
        _assert_request_id(invalid.headers["x-request-id"])
        self.assertNotEqual(invalid.headers["x-request-id"], "bad/id secret")

    def test_validation_error_does_not_echo_request_input(self) -> None:
        secret_question = "PRIVATE-QUESTION-" + "x" * MAX_QUESTION_CHARS
        app = create_serving_api_app(system=_FakeApiSystem())

        with _client(app) as client:
            response = client.post(
                "/answers",
                json={"question": secret_question},
                headers={"X-Request-ID": "validation-42"},
            )

        payload = _assert_error_response(
            response,
            status_code=422,
            code="VALIDATION_ERROR",
            request_id="validation-42",
        )
        self.assertNotIn(secret_question, json.dumps(payload, ensure_ascii=False))
        self.assertEqual(
            payload["error"]["details"],
            [{"field": "body.question", "reason": "string_too_long"}],
        )

    def test_unknown_exception_returns_internal_error_without_raw_text(self) -> None:
        secret = "provider-secret-error-body"
        app = create_serving_api_app(system=_FakeApiSystem())

        @app.get("/_test/boom")
        def boom():
            raise RuntimeError(secret)

        with _client(app) as client:
            response = client.get("/_test/boom", headers={"X-Request-ID": "boom-42"})

        payload = _assert_error_response(
            response,
            status_code=500,
            code="INTERNAL_ERROR",
            request_id="boom-42",
        )
        self.assertNotIn(secret, json.dumps(payload))
        self.assertNotIn("RuntimeError", json.dumps(payload))

    def test_not_found_and_method_not_allowed_use_the_common_contract(self) -> None:
        app = create_serving_api_app(system=_FakeApiSystem())

        with _client(app) as client:
            missing = client.get("/does-not-exist")
            method = client.put("/health")

        _assert_error_response(missing, status_code=404, code="NOT_FOUND")
        _assert_error_response(method, status_code=405, code="METHOD_NOT_ALLOWED")

    def test_openapi_uses_the_common_error_schema(self) -> None:
        config = build_test_config({"api": {"access_token": _API_TOKEN, "openapi_enabled": True}})
        app = create_serving_api_app(system=_FakeApiSystem(), config=config)

        with _client(app) as client:
            schema = client.get("/openapi.json").json()

        self.assertIn("ErrorResponseModel", schema["components"]["schemas"])
        validation_schema = schema["paths"]["/answers"]["post"]["responses"]["422"]
        self.assertEqual(
            validation_schema["content"]["application/json"]["schema"]["$ref"],
            "#/components/schemas/ErrorResponseModel",
        )

    def test_failed_answer_becomes_typed_500_without_raw_exception(self) -> None:
        secret = "answer-provider-secret"
        app = create_serving_api_app(system=_FailedAnswerSystem(secret))

        with _client(app) as client:
            response = client.post(
                "/answers",
                json={"question": "safe question"},
                headers={"X-Request-ID": "answer-failed-42"},
            )

        payload = _assert_error_response(
            response,
            status_code=500,
            code="ANSWER_FAILED",
            request_id="answer-failed-42",
        )
        self.assertNotIn(secret, json.dumps(payload))

    def test_sse_error_uses_common_contract_and_request_id(self) -> None:
        secret = "stream-provider-secret"
        app = create_serving_api_app(system=_FailedAnswerSystem(secret))

        with _client(app) as client:
            with client.stream(
                "POST",
                "/answers/stream",
                json={"question": "safe question"},
                headers={"X-Request-ID": "stream-failed-42"},
            ) as response:
                body = "".join(response.iter_text())

        self.assertEqual(response.status_code, 200)
        self.assertIn("event: error", body)
        self.assertIn('"code": "ANSWER_FAILED"', body)
        self.assertIn('"request_id": "stream-failed-42"', body)
        self.assertNotIn("error_type", body)
        self.assertNotIn(secret, body)
        self.assertIn("event: done", body)

    def test_stream_preflight_failure_uses_http_error_contract(self) -> None:
        app = create_serving_api_app(system=_FakeApiSystem())

        with _client(app) as client:
            response = client.post(
                "/answers/stream",
                json={"question": "safe question"},
            )

        _assert_error_response(response, status_code=409, code="SYSTEM_NOT_READY")

    def test_serving_liveness_is_public_and_does_not_require_readiness(self) -> None:
        app = create_serving_api_app(system=_FakeApiSystem())

        with TestClient(app) as client:
            response = client.get("/health/live")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ok")
        self.assertFalse(response.json()["system_ready"])

    def test_owned_serving_api_fails_startup_when_model_api_key_is_missing(self) -> None:
        config = build_test_config({"models": {"api_key": ""}})
        app = create_serving_api_app(config=config)

        with self.assertRaisesRegex(ValueError, "DASHSCOPE_API_KEY"):
            with TestClient(app):
                pass

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

    def test_manifest_error_is_sanitized_in_diagnostics_and_stats(self) -> None:
        secret = "private-manifest-error"
        app = create_serving_api_app(system=_PublicManifestErrorSystem(secret))

        with _client(app) as client:
            diagnostics = client.get("/diagnostics")
            stats = client.get("/stats")

        serialized = json.dumps(
            {"diagnostics": diagnostics.json(), "stats": stats.json()},
            ensure_ascii=False,
        )
        self.assertNotIn(secret, serialized)
        self.assertIn("BUILD_FAILED", serialized)

    def test_build_diagnostics_include_safe_build_job_store_warning_summary(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = build_test_config(
                {
                    "api": {"access_token": _API_TOKEN},
                    "storage": {
                        "artifact_manifest_path": str(root / "manifest.json"),
                        "build_job_store_path": str(root / "jobs.json"),
                    },
                }
            )
            system = _FakeApiSystem()
            system.config = config
            repository_dir = root / "jobs.d" / "jobs"
            repository_dir.mkdir(parents=True)
            (repository_dir / f"{'6' * 32}.json").write_text(
                "{broken secret-diagnostics-value",
                encoding="utf-8",
            )
            app = create_build_api_app(system=system, config=config)

            with _client(app) as client:
                response = client.get("/diagnostics")

        self.assertEqual(response.status_code, 200)
        payload = response.json()["diagnostics"]["build_job_store"]
        dumped = json.dumps(response.json(), ensure_ascii=False)
        self.assertGreaterEqual(payload["warning_count"], 1)
        self.assertIn("BUILD_JOB_STORE_CORRUPT_RECORD", payload["warning_codes"])
        self.assertNotIn("secret-diagnostics-value", dumped)

    def test_build_diagnostics_include_corrupt_idempotency_warning_summary(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = build_test_config(
                {
                    "api": {"access_token": _API_TOKEN},
                    "storage": {
                        "artifact_manifest_path": str(root / "manifest.json"),
                        "build_job_store_path": str(root / "jobs.json"),
                    },
                }
            )
            system = _FakeApiSystem()
            system.config = config
            idempotency_dir = root / "jobs.d" / "idempotency"
            idempotency_dir.mkdir(parents=True)
            (idempotency_dir / "bad-index.json").write_text(
                '["secret-idempotency-value"]',
                encoding="utf-8",
            )
            app = create_build_api_app(system=system, config=config)

            with _client(app) as client:
                response = client.get("/diagnostics")

        self.assertEqual(response.status_code, 200)
        payload = response.json()["diagnostics"]["build_job_store"]
        dumped = json.dumps(response.json(), ensure_ascii=False)
        self.assertGreaterEqual(payload["warning_count"], 1)
        self.assertIn("BUILD_JOB_STORE_CORRUPT_IDEMPOTENCY", payload["warning_codes"])
        self.assertNotIn("secret-idempotency-value", dumped)

    def test_build_jobs_skip_invalid_job_records_instead_of_returning_500(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = build_test_config(
                {
                    "api": {"access_token": _API_TOKEN},
                    "storage": {
                        "artifact_manifest_path": str(root / "manifest.json"),
                        "build_job_store_path": str(root / "jobs.json"),
                    },
                }
            )
            system = _FakeApiSystem()
            system.config = config
            jobs_dir = root / "jobs.d" / "jobs"
            jobs_dir.mkdir(parents=True)
            (jobs_dir / f"{'9' * 32}.json").write_text(
                json.dumps(
                    {
                        "job_id": "9" * 32,
                        "request_id": "secret-invalid-job",
                        "job_type": "build",
                        "status": "not-a-status",
                        "created_at": "2026-06-29T00:00:00Z",
                    }
                ),
                encoding="utf-8",
            )
            app = create_build_api_app(system=system, config=config)

            with TestClient(
                app,
                headers={"Authorization": f"Bearer {_API_TOKEN}"},
                raise_server_exceptions=False,
            ) as client:
                jobs_response = client.get("/jobs")
                diagnostics_response = client.get("/diagnostics")

        self.assertEqual(jobs_response.status_code, 200)
        self.assertEqual(jobs_response.json()["jobs"], [])
        payload = diagnostics_response.json()["diagnostics"]["build_job_store"]
        dumped = json.dumps(
            {"jobs": jobs_response.json(), "diagnostics": diagnostics_response.json()},
            ensure_ascii=False,
        )
        self.assertIn("BUILD_JOB_STORE_CORRUPT_RECORD", payload["warning_codes"])
        self.assertNotIn("secret-invalid-job", dumped)

    def test_serving_answer_returns_409_when_artifacts_are_not_ready(self) -> None:
        system = _FakeApiSystem()
        app = create_serving_api_app(system=system)

        with _client(app) as client:
            response = client.post("/answers", json={"question": "Can I cook tofu?"})

        _assert_error_response(response, status_code=409, code="SYSTEM_NOT_READY")
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

    def test_build_jobs_surface_paginates_jobs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config = build_test_config(
                {
                    "api": {
                        "access_token": _API_TOKEN,
                        "build_job_list_default_limit": 2,
                        "build_job_list_max_limit": 2,
                    },
                    "storage": {
                        "artifact_manifest_path": str(Path(temp_dir) / "manifest.json"),
                        "build_job_store_path": str(Path(temp_dir) / "jobs.json"),
                    },
                }
            )
            system = _FakeApiSystem()
            system.config = config
            app = create_build_api_app(system=system, config=config)

            with _client(app) as client:
                job_ids: list[str] = []
                for _ in range(3):
                    submitted = client.post("/jobs/build").json()["job"]
                    finished = _wait_for_job_status(client, submitted["job_id"], "succeeded")
                    job_ids.append(finished["job_id"])
                first_page = client.get("/jobs", params={"limit": 2})
                cursor = first_page.json()["next_cursor"]
                second_page = client.get("/jobs", params={"limit": 2, "cursor": cursor})

        self.assertEqual(first_page.status_code, 200)
        self.assertEqual(second_page.status_code, 200)
        self.assertEqual(
            [job["job_id"] for job in first_page.json()["jobs"]], list(reversed(job_ids))[0:2]
        )
        self.assertTrue(cursor)
        self.assertEqual(
            [job["job_id"] for job in second_page.json()["jobs"]], list(reversed(job_ids))[2:3]
        )
        self.assertEqual(second_page.json()["next_cursor"], "")

    def test_build_jobs_surface_rejects_invalid_cursor(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config = build_test_config(
                {
                    "api": {"access_token": _API_TOKEN},
                    "storage": {
                        "artifact_manifest_path": str(Path(temp_dir) / "manifest.json"),
                        "build_job_store_path": str(Path(temp_dir) / "jobs.json"),
                    },
                }
            )
            system = _FakeApiSystem()
            system.config = config
            app = create_build_api_app(system=system, config=config)

            with _client(app) as client:
                response = client.get("/jobs", params={"cursor": "not-a-cursor"})

        self.assertEqual(response.status_code, 400)
        payload = response.json()
        self.assertEqual(payload["error"]["code"], "INVALID_REQUEST")
        self.assertEqual(payload["error"]["details"]["field"], "cursor")

    def test_v1_build_jobs_accept_idempotency_and_paginated_list_shape(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config = build_test_config(
                {
                    "api": {"access_token": _API_TOKEN},
                    "storage": {
                        "artifact_manifest_path": str(Path(temp_dir) / "manifest.json"),
                        "build_job_store_path": str(Path(temp_dir) / "jobs.json"),
                    },
                }
            )
            system = _FakeApiSystem()
            system.config = config
            app = create_build_api_app(system=system, config=config)

            with _client(app) as client:
                first = client.post("/v1/jobs/build", headers={"Idempotency-Key": "v1-key"})
                job_id = first.json()["job"]["job_id"]
                _wait_for_job_status(client, job_id, "succeeded")
                repeated = client.post("/v1/jobs/build", headers={"Idempotency-Key": "v1-key"})
                listed = client.get("/v1/jobs", params={"limit": 1})

        self.assertEqual(repeated.json()["job"]["job_id"], job_id)
        self.assertIn("next_cursor", listed.json())

    def test_knowledge_base_build_alias_accepts_idempotency_key(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config = build_test_config(
                {
                    "api": {"access_token": _API_TOKEN},
                    "storage": {
                        "artifact_manifest_path": str(Path(temp_dir) / "manifest.json"),
                        "build_job_store_path": str(Path(temp_dir) / "jobs.json"),
                    },
                }
            )
            system = _FakeApiSystem()
            system.config = config
            app = create_build_api_app(system=system, config=config)

            with _client(app) as client:
                first = client.post(
                    "/knowledge-base/build",
                    headers={"Idempotency-Key": "alias-key"},
                )
                job_id = first.json()["job"]["job_id"]
                _wait_for_job_status(client, job_id, "succeeded")
                repeated = client.post(
                    "/knowledge-base/build",
                    headers={"Idempotency-Key": "alias-key"},
                )

        self.assertEqual(repeated.json()["job"]["job_id"], job_id)

    def test_build_jobs_surface_reuses_idempotency_key_for_same_job_type(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config = build_test_config(
                {
                    "api": {"access_token": _API_TOKEN},
                    "storage": {
                        "artifact_manifest_path": str(Path(temp_dir) / "manifest.json"),
                        "build_job_store_path": str(Path(temp_dir) / "jobs.json"),
                    },
                }
            )
            system = _FakeApiSystem()
            system.config = config
            app = create_build_api_app(system=system, config=config)

            with _client(app) as client:
                first_response = client.post(
                    "/jobs/build",
                    headers={"Idempotency-Key": "retry-key-1"},
                )
                first_job = first_response.json()["job"]
                _wait_for_job_status(client, first_job["job_id"], "succeeded")
                second_response = client.post(
                    "/jobs/build",
                    headers={"Idempotency-Key": "retry-key-1"},
                )

        self.assertEqual(first_response.status_code, 202)
        self.assertEqual(second_response.status_code, 202)
        self.assertEqual(second_response.json()["job"]["job_id"], first_job["job_id"])
        self.assertEqual(system.build_calls, 1)

    def test_build_jobs_surface_rejects_idempotency_key_reused_for_different_type(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config = build_test_config(
                {
                    "api": {"access_token": _API_TOKEN},
                    "storage": {
                        "artifact_manifest_path": str(Path(temp_dir) / "manifest.json"),
                        "build_job_store_path": str(Path(temp_dir) / "jobs.json"),
                    },
                }
            )
            system = _FakeApiSystem()
            system.config = config
            app = create_build_api_app(system=system, config=config)

            with _client(app) as client:
                first_response = client.post(
                    "/jobs/build",
                    headers={"Idempotency-Key": "retry-key-2"},
                )
                first_job = first_response.json()["job"]
                _wait_for_job_status(client, first_job["job_id"], "succeeded")
                conflict_response = client.post(
                    "/jobs/rebuild",
                    headers={"Idempotency-Key": "retry-key-2"},
                )

        payload = _assert_error_response(
            conflict_response,
            status_code=409,
            code="BUILD_JOB_CONFLICT",
        )
        self.assertEqual(payload["error"]["details"]["job_id"], first_job["job_id"])
        self.assertEqual(payload["error"]["details"]["job_type"], "build")

    def test_build_jobs_surface_rejects_invalid_idempotency_key(self) -> None:
        app = create_build_api_app(system=_FakeApiSystem())

        with _client(app) as client:
            response = client.post("/jobs/build", headers={"Idempotency-Key": "../bad"})

        payload = _assert_error_response(response, status_code=400, code="INVALID_REQUEST")
        self.assertEqual(payload["error"]["details"]["field"], "Idempotency-Key")

    def test_build_jobs_surface_replays_active_job_with_same_idempotency_key(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config = build_test_config(
                {
                    "api": {"access_token": _API_TOKEN},
                    "storage": {
                        "artifact_manifest_path": str(Path(temp_dir) / "manifest.json"),
                        "build_job_store_path": str(Path(temp_dir) / "jobs.json"),
                    },
                }
            )
            system = _BlockingBuildApiSystem()
            system.config = config
            app = create_build_api_app(system=system, config=config)

            with _client(app) as client:
                first_response = client.post(
                    "/jobs/build",
                    headers={"Idempotency-Key": "active-key-1"},
                )
                first_job = first_response.json()["job"]
                self.assertTrue(system.build_started.wait(timeout=1.0))

                replay_response = client.post(
                    "/jobs/build",
                    headers={"Idempotency-Key": "active-key-1"},
                )

                system.release_build.set()
                _wait_for_job_status(client, first_job["job_id"], "succeeded")

        self.assertEqual(first_response.status_code, 202)
        self.assertEqual(replay_response.status_code, 202)
        self.assertEqual(replay_response.json()["job"]["job_id"], first_job["job_id"])
        self.assertEqual(system.build_calls, 1)

    def test_rejected_idempotency_key_does_not_reserve_key(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config = build_test_config(
                {
                    "api": {"access_token": _API_TOKEN},
                    "storage": {
                        "artifact_manifest_path": str(Path(temp_dir) / "manifest.json"),
                        "build_job_store_path": str(Path(temp_dir) / "jobs.json"),
                    },
                }
            )
            system = _BlockingBuildApiSystem()
            system.config = config
            app = create_build_api_app(system=system, config=config)

            with _client(app) as client:
                first_response = client.post(
                    "/jobs/build",
                    headers={"Idempotency-Key": "active-key-2"},
                )
                first_job = first_response.json()["job"]
                self.assertTrue(system.build_started.wait(timeout=1.0))

                conflict_response = client.post(
                    "/jobs/rebuild",
                    headers={"Idempotency-Key": "later-key"},
                )

                system.release_build.set()
                _wait_for_job_status(client, first_job["job_id"], "succeeded")
                accepted_response = client.post(
                    "/jobs/rebuild",
                    headers={"Idempotency-Key": "later-key"},
                )
                accepted_job = accepted_response.json()["job"]
                _wait_for_job_status(client, accepted_job["job_id"], "succeeded")

        _assert_error_response(conflict_response, status_code=409, code="BUILD_JOB_CONFLICT")
        self.assertEqual(accepted_response.status_code, 202)
        self.assertNotEqual(accepted_job["job_id"], first_job["job_id"])

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
        conflict_payload = _assert_error_response(
            conflict_response,
            status_code=409,
            code="BUILD_JOB_CONFLICT",
        )
        self.assertEqual(conflict_payload["error"]["details"]["job_id"], first_job["job_id"])

    def test_build_http_failed_build_job_keeps_submission_request_id_without_secret(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config = build_test_config(
                {
                    "api": {"access_token": _API_TOKEN},
                    "storage": {
                        "artifact_manifest_path": str(Path(temp_dir) / "manifest.json"),
                        "build_job_store_path": str(Path(temp_dir) / "jobs.json"),
                    },
                }
            )
            secret = "build-http-secret"
            system = _FailingBuildApiSystem(secret)
            system.config = config
            app = create_build_api_app(system=system, config=config)

            with _client(app) as client:
                submitted = client.post(
                    "/jobs/build",
                    headers={"X-Request-ID": "build-http-42"},
                ).json()["job"]
                failed = _wait_for_job_status(client, submitted["job_id"], "failed")

        self.assertEqual(failed["request_id"], "build-http-42")
        self.assertEqual(failed["error"]["request_id"], "build-http-42")
        self.assertEqual(failed["error"]["code"], "BUILD_FAILED")
        self.assertNotIn(secret, json.dumps(failed, ensure_ascii=False))

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

    def test_v1_answer_omits_traces_by_default(self) -> None:
        system = _FakeApiSystem()
        system.system_ready = True
        app = create_serving_api_app(system=system)

        with _client(app) as client:
            response = client.post("/v1/answers", json={"question": "Can I cook tofu?"})

        self.assertEqual(response.status_code, 200)
        payload = response.json()["response"]
        self.assertEqual(payload["summary"]["answer"], "answer:Can I cook tofu?")
        self.assertNotIn("traces", payload)

    def test_v1_debug_answer_includes_traces(self) -> None:
        system = _FakeApiSystem()
        system.system_ready = True
        app = create_serving_api_app(system=system)

        with _client(app) as client:
            response = client.post("/v1/debug/answers", json={"question": "Can I cook tofu?"})

        self.assertEqual(response.status_code, 200)
        payload = response.json()["response"]
        self.assertEqual(
            payload["traces"]["generation_trace"]["token_usage_source"],
            "test",
        )

    def test_v1_answer_stream_result_omits_traces_by_default(self) -> None:
        system = _FakeApiSystem()
        system.system_ready = True
        app = create_serving_api_app(system=system)

        with _client(app) as client:
            with client.stream(
                "POST",
                "/v1/answers/stream",
                json={"question": "Can I cook tofu?"},
            ) as response:
                body = "".join(response.iter_text())

        self.assertEqual(response.status_code, 200)
        result_payload = _parse_sse_events(body)["result"][0]["response"]
        self.assertEqual(result_payload["summary"]["answer"], "answer:Can I cook tofu?")
        self.assertNotIn("traces", result_payload)

    def test_v1_debug_answer_stream_result_includes_traces(self) -> None:
        system = _FakeApiSystem()
        system.system_ready = True
        app = create_serving_api_app(system=system)

        with _client(app) as client:
            with client.stream(
                "POST",
                "/v1/debug/answers/stream",
                json={"question": "Can I cook tofu?"},
            ) as response:
                body = "".join(response.iter_text())

        self.assertEqual(response.status_code, 200)
        result_payload = _parse_sse_events(body)["result"][0]["response"]
        self.assertEqual(
            result_payload["traces"]["generation_trace"]["token_usage_source"],
            "test",
        )

    def test_serving_and_build_apps_share_api_version_constant(self) -> None:
        serving_app = create_serving_api_app(system=_FakeApiSystem())
        build_app = create_build_api_app(system=_FakeApiSystem())
        app_source = (
            Path(__file__).resolve().parents[1] / "rag_modules" / "interfaces" / "api" / "app.py"
        ).read_text(encoding="utf-8")

        self.assertEqual(serving_app.version, API_VERSION)
        self.assertEqual(build_app.version, API_VERSION)
        self.assertIn("version=API_VERSION", app_source)
        self.assertNotIn('version="1.0.0"', app_source)

    def test_v1_health_paths_are_public_and_protected_paths_stay_protected(self) -> None:
        app = create_serving_api_app(system=_FakeApiSystem())

        with TestClient(app) as client:
            health = client.get("/v1/health")
            stats = client.get("/v1/stats")
            debug = client.post("/v1/debug/answers", json={"question": "tofu"})

        self.assertEqual(health.status_code, 200)
        _assert_error_response(stats, status_code=401, code="UNAUTHORIZED")
        _assert_error_response(debug, status_code=401, code="UNAUTHORIZED")

    def test_v1_build_routes_match_unversioned_build_routes(self) -> None:
        system = _FakeApiSystem()
        app = create_build_api_app(system=system)

        with _client(app) as client:
            health = client.get("/v1/health")
            initialize = client.post("/v1/runtime/build/initialize")
            build_response = client.post("/v1/jobs/build")
            build_job = build_response.json().get("job", {})
            finished_job = _wait_for_job_status(
                client,
                build_job.get("job_id", ""),
                "succeeded",
            )
            list_response = client.get("/v1/jobs")
            artifacts = client.get("/v1/artifacts")

        self.assertEqual(health.status_code, 200)
        self.assertEqual(initialize.status_code, 200)
        self.assertEqual(build_response.status_code, 202)
        self.assertEqual(list_response.status_code, 200)
        self.assertEqual(artifacts.status_code, 200)
        self.assertEqual(list_response.json()["jobs"][0]["job_id"], build_job["job_id"])
        self.assertEqual(finished_job["result"]["message"], "Knowledge base build completed.")

    def test_openapi_security_metadata_clears_v1_health_and_keeps_debug_protected(self) -> None:
        config = build_test_config(
            {
                "api": {
                    "access_token": _API_TOKEN,
                    "openapi_enabled": True,
                }
            }
        )
        app = create_serving_api_app(system=_FakeApiSystem(), config=config)

        with _client(app) as client:
            schema = client.get("/openapi.json").json()

        self.assertEqual(schema["paths"]["/v1/health"]["get"]["security"], [])
        self.assertNotEqual(schema["paths"]["/v1/debug/answers"]["post"].get("security"), [])

    def test_openapi_distinguishes_public_and_debug_answer_schemas(self) -> None:
        config = build_test_config(
            {
                "api": {
                    "access_token": _API_TOKEN,
                    "openapi_enabled": True,
                }
            }
        )
        app = create_serving_api_app(system=_FakeApiSystem(), config=config)

        with _client(app) as client:
            schema = client.get("/openapi.json").json()

        public_response_ref = schema["paths"]["/v1/answers"]["post"]["responses"]["200"]["content"][
            "application/json"
        ]["schema"]["$ref"]
        debug_response_ref = schema["paths"]["/v1/debug/answers"]["post"]["responses"]["200"][
            "content"
        ]["application/json"]["schema"]["$ref"]

        self.assertEqual(public_response_ref, "#/components/schemas/PublicAnswerResponseModel")
        self.assertEqual(debug_response_ref, "#/components/schemas/AnswerResponseModel")
        self.assertNotIn(
            "traces",
            schema["components"]["schemas"]["PublicAnswerPayloadModel"]["properties"],
        )
        self.assertIn("traces", schema["components"]["schemas"]["AnswerPayloadModel"]["properties"])

    def test_answer_trace_error_fields_are_sanitized_on_success(self) -> None:
        secret = "private-answer-trace-error"
        app = create_serving_api_app(system=_PublicAnswerErrorSystem(secret))

        with _client(app) as client:
            response = client.post("/answers", json={"question": "safe question"})

        self.assertEqual(response.status_code, 200)
        serialized = json.dumps(response.json(), ensure_ascii=False)
        self.assertNotIn(secret, serialized)
        self.assertIn("ANSWER_FAILED", serialized)

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
        config = build_test_config(
            {
                "api": {
                    "access_token": _API_TOKEN,
                    "openapi_enabled": True,
                }
            }
        )
        app = create_serving_api_app(system=_FakeApiSystem(), config=config)

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
        result_payload = events["result"][0]["response"]
        self.assertEqual(result_payload["summary"]["prompt_tokens"], 11)
        self.assertEqual(
            result_payload["traces"]["generation_trace"]["token_usage_source"],
            "test",
        )
        self.assertEqual(
            result_payload["diagnostics"]["diagnostics"]["overall_bucket"],
            "ok",
        )
        self.assertEqual(events["done"][0]["ok"], True)

    def test_answer_http_and_sse_paths_do_not_call_application_to_dict(self) -> None:
        class _TypedResponseApiSystem(_FakeApiSystem):
            def answer_question_response(
                self,
                question: str,
                *,
                stream: bool = False,
                explain_routing: bool = False,
                message_callback=None,
                chunk_callback=None,
            ) -> QuestionAnswerResponse:
                if stream:
                    if message_callback:
                        message_callback("Running query routing...")
                    if chunk_callback:
                        chunk_callback("chunk-1")
                self.answer_calls.append((question, stream, explain_routing))
                return QuestionAnswerResult(
                    answer=f"answer:{question}",
                    analysis=None,
                    trace_event=QueryTraceEvent(query=question),
                ).to_response()

        system = _TypedResponseApiSystem()
        system.system_ready = True
        system.serving_initialized = True
        app = create_serving_api_app(system=system, config=_API_CONFIG)

        with patch.object(
            QuestionAnswerResponse,
            "to_dict",
            side_effect=AssertionError("application response serialized internally"),
        ):
            with _client(app) as client:
                answer_response = client.post("/answers", json={"question": "tofu"})
                stream_response = client.post("/answers/stream", json={"question": "tofu"})

        self.assertEqual(answer_response.status_code, 200)
        self.assertEqual(answer_response.json()["response"]["summary"]["answer"], "answer:tofu")
        self.assertEqual(stream_response.status_code, 200)
        self.assertIn("event: result", stream_response.text)

    def test_explicit_answer_stream_route_uses_sse_surface(self) -> None:
        system = _FakeApiSystem()
        system.system_ready = True
        config = build_test_config(
            {
                "api": {
                    "access_token": _API_TOKEN,
                    "openapi_enabled": True,
                }
            }
        )
        app = create_serving_api_app(system=system, config=config)

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
        schemas = schema["components"]["schemas"]
        self.assertIn("GenerationSnapshotResponseModel", schemas)
        self.assertIn("QueryTraceEventResponseModel", schemas)
        generation_schema = schemas["GenerationSnapshotResponseModel"]
        self.assertIn("token_usage_source", generation_schema["properties"])
        token_usage_schema = generation_schema["properties"]["token_usage_source"]
        self.assertEqual(token_usage_schema["type"], "string")
        self.assertEqual(token_usage_schema["default"], "")
        trace_event_schema = schemas["QueryTraceEventResponseModel"]
        self.assertIn("diagnostics", trace_event_schema["properties"])
        self.assertEqual(
            trace_event_schema["properties"]["diagnostics"]["$ref"],
            "#/components/schemas/QueryDiagnosticsResponseModel",
        )
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

        _assert_error_response(response, status_code=429, code="RATE_LIMITED")

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
        self.assertIn('"code": "RATE_LIMITED"', body)
        self.assertIn(f'"request_id": "{response.headers["x-request-id"]}"', body)
        self.assertNotIn("error_type", body)
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

    def test_pending_refresh_blocks_new_answers_until_active_answer_finishes(self) -> None:
        system = _LifecycleRaceApiSystem()
        service = GraphRAGServingApiService(system=system, config=_serving_race_config())
        lifecycle_requested = _observe_lifecycle_requests(service)
        first_done = threading.Event()
        refresh_done = threading.Event()
        second_done = threading.Event()
        errors: list[BaseException] = []

        def run_first_answer() -> None:
            try:
                service.answer_question(question="first tofu")
            except BaseException as exc:
                errors.append(exc)
            finally:
                first_done.set()

        def run_refresh() -> None:
            try:
                service.refresh_serving_runtime()
            except BaseException as exc:
                errors.append(exc)
            finally:
                refresh_done.set()

        def run_second_answer() -> None:
            try:
                service.answer_question(question="second tofu")
            except BaseException as exc:
                errors.append(exc)
            finally:
                second_done.set()

        first_thread = threading.Thread(target=run_first_answer)
        refresh_thread = threading.Thread(target=run_refresh)
        second_thread = threading.Thread(target=run_second_answer)
        first_thread.start()
        self.assertTrue(system.first_answer_started.wait(timeout=1.0))

        refresh_thread.start()
        self.assertTrue(lifecycle_requested.wait(timeout=1.0))

        second_thread.start()
        self.assertFalse(
            system.second_answer_started.wait(timeout=0.1),
            "new answers must not enter while a refresh is waiting for lifecycle access",
        )
        self.assertFalse(system.refresh_started.is_set())

        system.release_answers.set()
        first_thread.join(timeout=1.0)
        refresh_thread.join(timeout=1.0)
        second_thread.join(timeout=1.0)

        self.assertTrue(first_done.is_set())
        self.assertTrue(refresh_done.is_set())
        self.assertTrue(second_done.is_set())
        self.assertTrue(system.refresh_started.is_set())
        self.assertEqual(system.refresh_calls, 1)
        self.assertEqual(errors, [])

    def test_pending_shutdown_blocks_new_answers_until_active_answer_finishes(self) -> None:
        system = _LifecycleRaceApiSystem()
        service = GraphRAGServingApiService(system=system, config=_serving_race_config())
        lifecycle_requested = _observe_lifecycle_requests(service)
        first_done = threading.Event()
        shutdown_done = threading.Event()
        second_done = threading.Event()
        errors: list[BaseException] = []

        def run_first_answer() -> None:
            try:
                service.answer_question(question="first tofu")
            except BaseException as exc:
                errors.append(exc)
            finally:
                first_done.set()

        def run_shutdown() -> None:
            try:
                service.shutdown()
            except BaseException as exc:
                errors.append(exc)
            finally:
                shutdown_done.set()

        def run_second_answer() -> None:
            try:
                service.answer_question(question="second tofu")
            except BaseException:
                pass
            finally:
                second_done.set()

        first_thread = threading.Thread(target=run_first_answer)
        shutdown_thread = threading.Thread(target=run_shutdown)
        second_thread = threading.Thread(target=run_second_answer)
        first_thread.start()
        self.assertTrue(system.first_answer_started.wait(timeout=1.0))

        shutdown_thread.start()
        self.assertTrue(lifecycle_requested.wait(timeout=1.0))

        second_thread.start()
        self.assertFalse(
            system.second_answer_started.wait(timeout=0.1),
            "new answers must not enter while shutdown is waiting for lifecycle access",
        )

        system.release_answers.set()
        first_thread.join(timeout=1.0)
        shutdown_thread.join(timeout=1.0)
        second_thread.join(timeout=1.0)

        self.assertTrue(first_done.is_set())
        self.assertTrue(shutdown_done.is_set())
        self.assertTrue(second_done.is_set())
        self.assertTrue(system.close_started.is_set())
        self.assertFalse(system.second_answer_started.is_set())
        self.assertEqual(errors, [])

    def test_closing_stream_consumer_allows_pending_shutdown_to_complete(self) -> None:
        system = _ChunkFloodApiSystem()
        service = GraphRAGServingApiService(system=system, config=_serving_race_config())
        lifecycle_requested = _observe_lifecycle_requests(service)
        events = service.stream_answer_question_events(question="flooded tofu")
        first_event = next(events)
        shutdown_done = threading.Event()
        errors: list[BaseException] = []

        def run_shutdown() -> None:
            try:
                service.shutdown()
            except BaseException as exc:
                errors.append(exc)
            finally:
                shutdown_done.set()

        self.assertEqual(first_event.event, AnswerStreamEventType.message)
        shutdown_thread = threading.Thread(target=run_shutdown)
        shutdown_thread.start()
        self.assertTrue(lifecycle_requested.wait(timeout=1.0))
        self.assertFalse(shutdown_done.wait(timeout=0.1))

        events.close()

        shutdown_thread.join(timeout=1.0)
        self.assertTrue(system.answer_finished.wait(timeout=1.0))
        self.assertTrue(shutdown_done.is_set())
        self.assertEqual(system.close_calls, 1)
        self.assertEqual(errors, [])

    def test_shutdown_canceled_queued_sse_runner_finishes_consumer(self) -> None:
        system = _BlockingStreamApiSystem()
        config = build_test_config(
            {
                "api": {
                    "access_token": _API_TOKEN,
                    "serving_hot_refresh_enabled": False,
                    "stream_executor_max_workers": 1,
                    "stream_queue_max_size": 4,
                }
            }
        )
        service = GraphRAGServingApiService(system=system, config=config)
        first_events = service.stream_answer_question_events(question="first stream")
        first_event = next(first_events)
        second_events = service.stream_answer_question_events(question="second stream")
        second_done = threading.Event()
        shutdown_done = threading.Event()
        second_seen = []
        errors: list[BaseException] = []

        def read_second_stream() -> None:
            try:
                second_seen.extend(second_events)
            except BaseException as exc:
                errors.append(exc)
            finally:
                second_done.set()

        def run_shutdown() -> None:
            try:
                service.shutdown()
            except BaseException as exc:
                errors.append(exc)
            finally:
                shutdown_done.set()

        self.assertEqual(first_event.event, AnswerStreamEventType.message)
        self.assertTrue(system.first_stream_started.wait(timeout=1.0))
        second_thread = threading.Thread(target=read_second_stream, daemon=True)
        second_thread.start()
        time.sleep(0.05)
        self.assertFalse(system.second_stream_started.is_set())

        shutdown_thread = threading.Thread(target=run_shutdown)
        shutdown_thread.start()
        system.release_streams.set()
        shutdown_thread.join(timeout=1.0)
        first_events.close()

        self.assertTrue(shutdown_done.is_set())
        self.assertTrue(
            second_done.wait(timeout=1.0),
            "SSE consumers should receive a terminal event when shutdown cancels a queued runner",
        )
        self.assertEqual(
            [event.event for event in second_seen],
            [AnswerStreamEventType.error, AnswerStreamEventType.done],
        )
        self.assertFalse(system.second_stream_started.is_set())
        self.assertEqual(errors, [])

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

    def test_docs_and_openapi_are_disabled_by_default(self) -> None:
        app = create_serving_api_app(system=_FakeApiSystem(), config=_API_CONFIG)

        with TestClient(app) as client:
            docs_response = client.get("/docs")
            redoc_response = client.get("/redoc")
            openapi_response = client.get("/openapi.json")

        self.assertEqual(docs_response.status_code, 404)
        self.assertEqual(redoc_response.status_code, 404)
        self.assertEqual(openapi_response.status_code, 404)

    def test_enabled_docs_and_openapi_require_credentials_by_default(self) -> None:
        config = build_test_config(
            {
                "api": {
                    "access_token": _API_TOKEN,
                    "docs_enabled": True,
                    "openapi_enabled": True,
                }
            }
        )
        app = create_serving_api_app(system=_FakeApiSystem(), config=config)

        with TestClient(app) as anonymous:
            docs_unauthorized = anonymous.get("/docs")
            openapi_unauthorized = anonymous.get("/openapi.json")
        with _client(app) as authenticated:
            docs_authorized = authenticated.get("/docs")
            openapi_authorized = authenticated.get("/openapi.json")

        self.assertEqual(docs_unauthorized.status_code, 401)
        self.assertEqual(openapi_unauthorized.status_code, 401)
        self.assertEqual(docs_authorized.status_code, 200)
        self.assertEqual(openapi_authorized.status_code, 200)

    def test_docs_and_openapi_can_be_made_public(self) -> None:
        config = build_test_config(
            {
                "api": {
                    "access_token": _API_TOKEN,
                    "docs_enabled": True,
                    "openapi_enabled": True,
                    "docs_public": True,
                    "openapi_public": True,
                }
            }
        )
        app = create_serving_api_app(system=_FakeApiSystem(), config=config)

        with TestClient(app) as client:
            docs_response = client.get("/docs")
            openapi_response = client.get("/openapi.json")

        self.assertEqual(docs_response.status_code, 200)
        self.assertEqual(openapi_response.status_code, 200)

    def test_openapi_security_metadata_only_clears_public_paths(self) -> None:
        config = build_test_config(
            {
                "api": {
                    "access_token": _API_TOKEN,
                    "openapi_enabled": True,
                }
            }
        )
        app = create_serving_api_app(system=_FakeApiSystem(), config=config)

        with _client(app) as client:
            schema = client.get("/openapi.json").json()

        self.assertEqual(schema["security"], [{"BearerAuth": []}, {"ApiKeyAuth": []}])
        self.assertEqual(schema["paths"]["/health"]["get"]["security"], [])
        self.assertNotEqual(schema["paths"]["/stats"]["get"].get("security"), [])

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
        _assert_error_response(unauthorized_response, status_code=401, code="UNAUTHORIZED")
        _assert_error_response(invalid_response, status_code=401, code="UNAUTHORIZED")
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

        _assert_error_response(response, status_code=503, code="SERVICE_MISCONFIGURED")

    def test_authentication_rejects_weak_configured_token(self) -> None:
        config = build_test_config({"api": {"auth_enabled": True, "access_token": "too-short"}})
        app = create_serving_api_app(system=_FakeApiSystem(), config=config)

        with TestClient(app) as client:
            response = client.get(
                "/stats",
                headers={"Authorization": "Bearer too-short"},
            )

        _assert_error_response(response, status_code=503, code="SERVICE_MISCONFIGURED")

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

        _assert_error_response(oversized_body, status_code=413, code="REQUEST_TOO_LARGE")
        _assert_error_response(
            oversized_question,
            status_code=422,
            code="VALIDATION_ERROR",
        )
        _assert_error_response(blank_question, status_code=422, code="VALIDATION_ERROR")

    def test_prometheus_metrics_endpoint_requires_credentials_by_default(self) -> None:
        app = create_serving_api_app(system=_FakeApiSystem(), config=_API_CONFIG)

        with TestClient(app) as anonymous:
            unauthorized = anonymous.get("/metrics")
        with _client(app) as authenticated:
            authorized = authenticated.get("/metrics")

        self.assertEqual(unauthorized.status_code, 401)
        self.assertEqual(authorized.status_code, 200)
        self.assertIn("graphrag_queries_total", authorized.text)
        self.assertTrue(authorized.headers["content-type"].startswith("text/plain"))

    def test_prometheus_metrics_endpoint_can_be_made_public(self) -> None:
        config = build_test_config(
            {
                "api": {"access_token": _API_TOKEN},
                "observability": {"prometheus_public": True},
            }
        )
        app = create_serving_api_app(system=_FakeApiSystem(), config=config)

        with TestClient(app) as client:
            response = client.get("/metrics")

        self.assertEqual(response.status_code, 200)
        self.assertIn("graphrag_queries_total", response.text)

    def test_prometheus_metrics_endpoint_can_be_disabled(self) -> None:
        config = build_test_config(
            {
                "api": {"access_token": _API_TOKEN},
                "observability": {"enable_prometheus": False},
            }
        )
        app = create_serving_api_app(system=_FakeApiSystem(), config=config)

        with _client(app) as client:
            response = client.get("/metrics")

        self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()

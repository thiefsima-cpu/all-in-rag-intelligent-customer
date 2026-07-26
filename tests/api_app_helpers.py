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

from rag_modules.app.diagnostics import (
    ArtifactBuildMetadataDiagnostics,
    ArtifactManifestDiagnostics,
    StartupDiagnostics,
    TraceStatsDiagnostics,
)
from rag_modules.application.answering.answer_models import (
    QuestionAnswerResponse,
    QuestionAnswerResult,
)
from rag_modules.contracts import EvidenceDocument
from rag_modules.contracts.runtime import (
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
from rag_modules.contracts.runtime.errors import answer_error_detail
from rag_modules.interfaces.api import create_build_api_app, create_serving_api_app
from rag_modules.interfaces.api.answer_models import (
    MAX_QUESTION_CHARS,
    AnswerResponseModel,
    AnswerStreamEventType,
    PublicAnswerPayloadModel,
)
from rag_modules.interfaces.api.error_models import ErrorCode, build_error_payload
from rag_modules.interfaces.api.services import (
    GraphRAGBuildApiService,
    GraphRAGServingApiService,
)
from rag_modules.interfaces.api.versioning import API_VERSION
from rag_modules.kernel.artifacts import ARTIFACT_HEALTH_MISSING, ARTIFACT_HEALTH_READY
from rag_modules.runtime.build_jobs import InProcessBuildJobRunner
from tests.configuration_test_helpers import build_test_config

_API_TOKEN = "test-api-access-token"


def _api_test_config():
    return build_test_config({"api": {"access_token": _API_TOKEN}})


_API_CONFIG = _api_test_config()


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
        response = client.get(f"/v1/jobs/{job_id}")
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
        trace_stats=TraceStatsDiagnostics.from_payload(
            {"dropped_events": 0, "queued_events": 0, "async_enabled": True}
        ),
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
            build_metadata=ArtifactBuildMetadataDiagnostics(),
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
        entity_name="mapo tofu",
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
        self._response.summary.error = answer_error_detail(RuntimeError(self.secret))
        self._response.traces.route_trace.error = answer_error_detail(RuntimeError(self.secret))

    def to_dict(self) -> dict:
        return self._response.to_dict()


class _FakeApiSystem:
    def __init__(self, config=None) -> None:
        self.config = config or _api_test_config()
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

    def build_knowledge_base(
        self,
        progress=None,
        *,
        request_id: str = "",
        build_job_id: str = "",
    ) -> None:
        del progress, request_id, build_job_id
        self.build_calls += 1
        self.system_ready = True

    def rebuild_knowledge_base(
        self,
        progress=None,
        *,
        request_id: str = "",
        build_job_id: str = "",
    ) -> None:
        del progress, request_id, build_job_id
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
        control=None,
    ):
        del control
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
        safe_error = answer_error_detail(RuntimeError(self.secret))
        self._response.summary.error = safe_error
        self._response.traces.route_trace.error = safe_error
        self._response.traces.graph_trace.error = safe_error
        self._response.traces.trace_event.error = safe_error

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
        control=None,
    ):
        del message_callback, chunk_callback, control
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
        control=None,
    ):
        del message_callback, chunk_callback, control
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

    def build_knowledge_base(
        self,
        progress=None,
        *,
        request_id: str = "",
        build_job_id: str = "",
    ) -> None:
        del progress, request_id, build_job_id
        self.build_calls += 1
        self.build_started.set()
        self.release_build.wait(timeout=2.0)
        self.system_ready = True


class _FailingBuildApiSystem(_FakeApiSystem):
    def __init__(self, secret: str) -> None:
        super().__init__()
        self.build_initialized = True
        self.secret = secret
        self.received_build_request_id = ""
        self.received_build_job_id = ""

    def build_knowledge_base(
        self,
        progress=None,
        *,
        request_id: str = "",
        build_job_id: str = "",
    ) -> None:
        self.received_build_request_id = request_id
        self.received_build_job_id = build_job_id
        if progress:
            progress(f"private progress {self.secret}")
        raise RuntimeError(self.secret)


class _FailOnceBuildApiSystem(_FakeApiSystem):
    def __init__(self) -> None:
        super().__init__()
        self.build_initialized = True
        self.failures_remaining = 1

    def build_knowledge_base(
        self,
        progress=None,
        *,
        request_id: str = "",
        build_job_id: str = "",
    ) -> None:
        del progress, request_id, build_job_id
        self.build_calls += 1
        if self.failures_remaining:
            self.failures_remaining -= 1
            raise RuntimeError("first build attempt fails")
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
        control=None,
    ):
        del control
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


class _StreamingControlCapturingSystem(_FakeApiSystem):
    def __init__(self) -> None:
        super().__init__()
        self.system_ready = True
        self.serving_initialized = True
        self.last_control = None
        self.answer_started = threading.Event()
        self.answer_finished = threading.Event()

    def answer_question_response(
        self,
        question: str,
        *,
        stream: bool = False,
        explain_routing: bool = False,
        message_callback=None,
        chunk_callback=None,
        control=None,
    ):
        del question, explain_routing, message_callback
        self.last_control = control
        if stream and chunk_callback:
            chunk_callback("chunk-0")
        self.answer_started.set()
        deadline = time.time() + 2.0
        while time.time() < deadline:
            if control is not None and control.cancelled:
                break
            time.sleep(0.01)
        self.answer_finished.set()
        return _DummyAnswerResponse("slow stream", False, stream)


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
        control=None,
    ):
        del message_callback, chunk_callback, control
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
        control=None,
    ):
        del chunk_callback, control
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


__all__ = (
    "annotations",
    "json",
    "re",
    "tempfile",
    "threading",
    "time",
    "unittest",
    "contextmanager",
    "Path",
    "patch",
    "TestClient",
    "ValidationError",
    "ArtifactBuildMetadataDiagnostics",
    "ArtifactManifestDiagnostics",
    "StartupDiagnostics",
    "TraceStatsDiagnostics",
    "QuestionAnswerResponse",
    "QuestionAnswerResult",
    "build_test_config",
    "EvidenceDocument",
    "AnswerContext",
    "GenerationSnapshot",
    "GraphRetrievalSnapshot",
    "QueryAnalysis",
    "QueryDiagnostics",
    "QueryTraceEvent",
    "RetrievalOutcome",
    "RetrievalTraceSnapshot",
    "RouteResolution",
    "RouteSnapshot",
    "answer_error_detail",
    "create_build_api_app",
    "create_serving_api_app",
    "MAX_QUESTION_CHARS",
    "AnswerResponseModel",
    "AnswerStreamEventType",
    "PublicAnswerPayloadModel",
    "ErrorCode",
    "build_error_payload",
    "GraphRAGBuildApiService",
    "GraphRAGServingApiService",
    "API_VERSION",
    "ARTIFACT_HEALTH_MISSING",
    "ARTIFACT_HEALTH_READY",
    "InProcessBuildJobRunner",
    "_API_TOKEN",
    "_API_CONFIG",
    "_client",
    "_assert_error_response",
    "_assert_request_id",
    "_parse_sse_events",
    "_wait_for_job_status",
    "_wait_for_service_job_status",
    "_observe_lifecycle_requests",
    "_serving_race_config",
    "_diagnostics",
    "_answer_result",
    "_answer_response",
    "_answer_payload",
    "_payload_without_new_summary_fields",
    "_DummyAnswerResponse",
    "_FailedAnswerResponse",
    "_FakeApiSystem",
    "_FailedAnswerSystem",
    "_PublicManifestErrorSystem",
    "_ErrorTraceAnswerResponse",
    "_PublicAnswerErrorSystem",
    "_BlockingApiSystem",
    "_ConcurrentAnswerApiSystem",
    "_BlockingBuildApiSystem",
    "_FailingBuildApiSystem",
    "_FailOnceBuildApiSystem",
    "_ChunkFloodApiSystem",
    "_StreamingControlCapturingSystem",
    "_LifecycleRaceApiSystem",
    "_BlockingStreamApiSystem",
)

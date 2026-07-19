"""Debug answer client and observation normalization for the live quality gate."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from time import perf_counter
from typing import Any, Iterable, Iterator, Protocol
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

import requests
from pydantic import ValidationError

from rag_modules.interfaces.api.answer_models import AnswerResponseModel
from scripts.gates import GateCheckResult, GateFailureType

from .models import (
    LiveQualityCasePolicy,
    LiveQualityGatePolicy,
    LiveQualityGateSettings,
)
from .runtime_models import LiveQualityCaseRunResult, LiveQualityEvidence, LiveQualityObservation


class RequestIdFactory(Protocol):
    def __call__(self) -> object: ...


class Clock(Protocol):
    def __call__(self) -> float: ...


@dataclass(frozen=True)
class _SseEvent:
    name: str
    data: dict[str, Any]


_REQUEST_FAILED_CODE = "LIVE_QUALITY_REQUEST_FAILED"
_DEBUG_ANSWER_PATH = "/v1/debug/answers/stream"
_REQUIRED_PAYLOAD_FIELDS = frozenset({"summary", "grounding", "diagnostics", "traces"})
_REQUIRED_SUMMARY_FIELDS = frozenset(
    {
        "strategy",
        "latency_ms",
        "fallback_used",
        "prompt_tokens",
        "completion_tokens",
        "total_tokens",
        "estimated_cost_usd",
    }
)
_REQUIRED_GROUNDING_FIELDS = frozenset({"evidence_documents"})
_REQUIRED_EVIDENCE_DOCUMENT_FIELDS = frozenset({"recipe_name", "source", "content", "score"})
_REQUIRED_DIAGNOSTICS_FIELDS = frozenset({"diagnostics"})
_REQUIRED_QUERY_DIAGNOSTIC_FIELDS = frozenset({"retrieval_degraded"})
_REQUIRED_TRACE_FIELDS = frozenset({"route_trace", "generation_trace"})
_REQUIRED_ROUTE_TRACE_FIELDS = frozenset(
    {"strategy", "stages", "fallbacks", "diagnostics", "total_latency_ms"}
)
_REQUIRED_ROUTE_STAGE_FIELDS = frozenset({"sources"})
_REQUIRED_POST_PROCESS_FIELDS = frozenset(
    {"rerank_attempted", "rerank_succeeded", "rerank_latency_ms"}
)
_REQUIRED_ROUTE_DIAGNOSTIC_FIELDS = frozenset(
    {"used_fallback", "fallback_count", "retrieval_degraded"}
)
_REQUIRED_GENERATION_TRACE_FIELDS = frozenset(
    {
        "fallback_used",
        "total_latency_ms",
        "first_token_latency_ms",
        "total_tokens",
        "estimated_cost_usd",
    }
)


def normalize_live_quality_observation(
    case: LiveQualityCasePolicy,
    payload: dict[str, Any],
    *,
    ttft_ms: float,
    latency_ms: float,
) -> LiveQualityObservation:
    response = AnswerResponseModel.model_validate(payload)
    _require_explicit_live_quality_contract(response)

    answer = response.response
    summary = answer.summary
    public_diagnostics = answer.diagnostics.diagnostics
    route_trace = answer.traces.route_trace
    route_diagnostics = route_trace.diagnostics
    generation_trace = answer.traces.generation_trace
    post_process = route_trace.stages.get("post_process")
    if post_process is None:
        raise ValueError("live quality post-process stage is missing")
    if not math.isfinite(route_trace.total_latency_ms) or route_trace.total_latency_ms <= 0:
        raise ValueError("live quality retrieval latency is missing")
    if (
        not math.isfinite(generation_trace.total_latency_ms)
        or generation_trace.total_latency_ms <= 0
    ):
        raise ValueError("live quality generation latency is missing")
    if (
        not math.isfinite(generation_trace.first_token_latency_ms)
        or generation_trace.first_token_latency_ms <= 0
    ):
        raise ValueError("live quality generation first-token latency is missing")
    if post_process.rerank_attempted:
        if (
            post_process.rerank_latency_ms is None
            or not math.isfinite(post_process.rerank_latency_ms)
            or post_process.rerank_latency_ms <= 0
        ):
            raise ValueError("live quality rerank latency is missing")
    elif post_process.rerank_latency_ms is not None:
        raise ValueError("live quality rerank timing is inconsistent")

    evidence = tuple(
        LiveQualityEvidence(
            recipe_name=document.recipe_name,
            source=document.source,
            content=document.content,
            score=document.score,
        )
        for document in answer.grounding.evidence_documents
    )
    ranked_recipe_names = tuple(item.recipe_name for item in evidence if item.recipe_name)

    sources = {item.source for item in evidence if item.source}
    for stage in route_trace.stages.values():
        sources.update(source for source, count in stage.sources.items() if source and count > 0)

    fallback_used = (
        summary.fallback_used
        or route_diagnostics.used_fallback
        or route_diagnostics.fallback_count > 0
        or bool(route_trace.fallbacks)
        or generation_trace.fallback_used
    )
    retrieval_degraded = (
        public_diagnostics.retrieval_degraded or route_diagnostics.retrieval_degraded
    )

    return LiveQualityObservation(
        case_id=case.case_id,
        answer=summary.answer,
        strategy=summary.strategy or route_trace.strategy,
        evidence=evidence,
        ranked_recipe_names=ranked_recipe_names,
        sources=frozenset(sources),
        fallback_used=fallback_used,
        retrieval_degraded=retrieval_degraded,
        ttft_ms=ttft_ms,
        latency_ms=latency_ms,
        retrieval_latency_ms=route_trace.total_latency_ms,
        rerank_attempted=post_process.rerank_attempted,
        rerank_succeeded=post_process.rerank_succeeded,
        rerank_latency_ms=post_process.rerank_latency_ms,
        generation_latency_ms=generation_trace.total_latency_ms,
        generation_first_token_latency_ms=generation_trace.first_token_latency_ms,
        prompt_tokens=summary.prompt_tokens,
        completion_tokens=summary.completion_tokens,
        total_tokens=generation_trace.total_tokens or summary.total_tokens,
        estimated_cost_usd=generation_trace.estimated_cost_usd or summary.estimated_cost_usd,
    )


def _require_explicit_live_quality_contract(response: AnswerResponseModel) -> None:
    payload = response.response
    traces = payload.traces
    route_trace = traces.route_trace
    generation_trace = traces.generation_trace
    post_process = route_trace.stages.get("post_process")
    if post_process is None:
        raise ValueError("live quality post-process stage is missing")

    if not (
        _fields_were_explicitly_set(payload, _REQUIRED_PAYLOAD_FIELDS)
        and _fields_were_explicitly_set(payload.summary, _REQUIRED_SUMMARY_FIELDS)
        and _fields_were_explicitly_set(payload.grounding, _REQUIRED_GROUNDING_FIELDS)
        and _items_were_explicitly_set(
            payload.grounding.evidence_documents,
            _REQUIRED_EVIDENCE_DOCUMENT_FIELDS,
        )
        and _fields_were_explicitly_set(payload.diagnostics, _REQUIRED_DIAGNOSTICS_FIELDS)
        and _fields_were_explicitly_set(
            payload.diagnostics.diagnostics,
            _REQUIRED_QUERY_DIAGNOSTIC_FIELDS,
        )
        and _fields_were_explicitly_set(traces, _REQUIRED_TRACE_FIELDS)
        and _fields_were_explicitly_set(route_trace, _REQUIRED_ROUTE_TRACE_FIELDS)
        and _items_were_explicitly_set(route_trace.stages.values(), _REQUIRED_ROUTE_STAGE_FIELDS)
        and _fields_were_explicitly_set(post_process, _REQUIRED_POST_PROCESS_FIELDS)
        and _fields_were_explicitly_set(route_trace.diagnostics, _REQUIRED_ROUTE_DIAGNOSTIC_FIELDS)
        and _fields_were_explicitly_set(generation_trace, _REQUIRED_GENERATION_TRACE_FIELDS)
    ):
        raise ValueError("live quality debug answer response is missing required contract fields")


def _fields_were_explicitly_set(model: object, required_fields: frozenset[str]) -> bool:
    fields_set = getattr(model, "model_fields_set", frozenset())
    return required_fields <= fields_set


def _items_were_explicitly_set(
    models: object,
    required_fields: frozenset[str],
) -> bool:
    materialized_models = tuple(models)
    return bool(materialized_models) and all(
        _fields_were_explicitly_set(model, required_fields) for model in materialized_models
    )


def run_live_case(
    *,
    settings: LiveQualityGateSettings,
    policy: LiveQualityGatePolicy,
    case: LiveQualityCasePolicy,
    http_session: requests.Session | None = None,
    request_id_factory: RequestIdFactory | None = None,
    clock: Clock = perf_counter,
) -> LiveQualityCaseRunResult:
    session = http_session if http_session is not None else requests.Session()
    owns_session = http_session is None
    started: float | None = None

    try:
        started = _sample_clock(clock)
        payload, ttft_ms, latency_ms = _post_debug_answer_stream(
            settings=settings,
            policy=policy,
            case=case,
            session=session,
            request_id_factory=request_id_factory,
            clock=clock,
            started=started,
        )
        observation = normalize_live_quality_observation(
            case,
            payload,
            ttft_ms=ttft_ms,
            latency_ms=latency_ms,
        )
    except (requests.RequestException, OSError, ValueError, ValidationError):
        duration_ms = _failure_duration_ms(clock, started)
        return LiveQualityCaseRunResult(
            case_id=case.case_id,
            observation=None,
            checks=(
                GateCheckResult.fail_check(
                    "live_quality_debug_answer_request",
                    failure_type=GateFailureType.DEPENDENCY_UNAVAILABLE,
                    code=_REQUEST_FAILED_CODE,
                    expected={"endpoint": _DEBUG_ANSWER_PATH},
                    actual={"case_id": case.case_id, "result": "request_failed"},
                    duration_ms=duration_ms,
                ),
            ),
        )
    finally:
        if owns_session:
            session.close()

    return LiveQualityCaseRunResult(case_id=case.case_id, observation=observation, checks=())


def _post_debug_answer_stream(
    *,
    settings: LiveQualityGateSettings,
    policy: LiveQualityGatePolicy,
    case: LiveQualityCasePolicy,
    session: requests.Session,
    request_id_factory: RequestIdFactory | None,
    clock: Clock,
    started: float,
) -> tuple[dict[str, Any], float, float]:
    request_id = request_id_factory() if request_id_factory is not None else uuid4()
    headers = {"X-Request-ID": f"live-quality-gate-{request_id}"}
    if settings.api_token:
        headers["Authorization"] = f"Bearer {settings.api_token}"

    response = session.post(
        _build_debug_answer_url(settings.api_url),
        json={"question": case.query, "explain_routing": True},
        headers=headers,
        timeout=policy.timeouts.request_seconds,
        stream=True,
    )
    try:
        response.raise_for_status()
        content_type = response.headers.get("content-type", "")
        if not content_type.lower().startswith("text/event-stream"):
            raise ValueError("live quality response is not an SSE stream")

        chunks: list[str] = []
        ttft_ms: float | None = None
        result_payload: dict[str, Any] | None = None
        response_latency_ms: float | None = None
        done = False

        for event in _iter_sse_events(response.iter_lines(decode_unicode=True)):
            if done:
                raise ValueError("live quality SSE event received after done")
            if result_payload is not None and event.name != "done":
                raise ValueError("live quality SSE event received after result")
            if event.name == "message":
                if set(event.data) != {"message"} or not isinstance(event.data["message"], str):
                    raise ValueError("invalid live quality SSE message event")
            elif event.name == "chunk":
                if set(event.data) != {"content"} or not isinstance(event.data["content"], str):
                    raise ValueError("invalid live quality SSE chunk event")
                content = event.data["content"]
                if content:
                    if ttft_ms is None:
                        ttft_ms = _elapsed_ms(clock, started)
                    chunks.append(content)
            elif event.name == "result":
                if result_payload is not None:
                    raise ValueError("duplicate live quality SSE result event")
                if set(event.data) != {"response"}:
                    raise ValueError("invalid live quality SSE result event")
                result_payload = event.data
                response_latency_ms = _elapsed_ms(clock, started)
            elif event.name == "error":
                raise ValueError("live quality SSE error event")
            elif event.name == "done":
                if event.data != {"ok": True}:
                    raise ValueError("invalid live quality SSE done event")
                done = True
            else:
                raise ValueError("unsupported live quality SSE event")

        if ttft_ms is None:
            raise ValueError("live quality SSE stream has no non-empty chunk")
        if result_payload is None or response_latency_ms is None:
            raise ValueError("live quality SSE stream is missing result")
        if not done:
            raise ValueError("live quality SSE stream is missing done")
        if ttft_ms > response_latency_ms:
            raise ValueError("live quality TTFT exceeds response latency")

        result_response = result_payload.get("response")
        summary = result_response.get("summary") if isinstance(result_response, dict) else None
        answer = summary.get("answer") if isinstance(summary, dict) else None
        if not isinstance(answer, str):
            raise ValueError("live quality SSE result answer is missing")
        if "".join(chunks) != answer:
            raise ValueError("live quality SSE chunks do not match result answer")
        return result_payload, ttft_ms, response_latency_ms
    finally:
        response.close()


def _iter_sse_events(lines: Iterable[str | bytes]) -> Iterator[_SseEvent]:
    event_name = ""
    data_lines: list[str] = []
    frame_started = False
    for raw_line in lines:
        line = raw_line.decode("utf-8") if isinstance(raw_line, bytes) else raw_line
        line = line.removesuffix("\r")
        if line == "":
            if not frame_started:
                continue
            if not event_name or not data_lines:
                raise ValueError("incomplete live quality SSE event")
            payload = json.loads("\n".join(data_lines))
            if not isinstance(payload, dict):
                raise ValueError("live quality SSE data must be an object")
            yield _SseEvent(name=event_name, data=payload)
            event_name = ""
            data_lines = []
            frame_started = False
            continue
        if line.startswith(":"):
            continue
        field, separator, value = line.partition(":")
        if not separator:
            raise ValueError("invalid live quality SSE field")
        value = value[1:] if value.startswith(" ") else value
        if field == "event":
            if event_name:
                raise ValueError("duplicate live quality SSE event field")
            event_name = value
            frame_started = True
        elif field == "data":
            data_lines.append(value)
            frame_started = True
        else:
            raise ValueError("unsupported live quality SSE field")
    if frame_started:
        raise ValueError("unterminated live quality SSE event")


def _elapsed_ms(clock: Clock, started: float) -> float:
    elapsed = (_sample_clock(clock) - started) * 1000
    if not math.isfinite(elapsed) or elapsed <= 0:
        raise ValueError("invalid live quality client timing")
    return elapsed


def _sample_clock(clock: Clock) -> float:
    try:
        raw_sample = clock()
        if isinstance(raw_sample, bool) or not isinstance(raw_sample, int | float):
            raise ValueError("invalid live quality clock sample")
        sample = float(raw_sample)
    except Exception as exc:
        raise ValueError("invalid live quality clock sample") from exc
    if not math.isfinite(sample):
        raise ValueError("invalid live quality clock sample")
    return sample


def _failure_duration_ms(clock: Clock, started: float | None) -> float:
    if started is None:
        return 0.0
    try:
        duration_ms = (_sample_clock(clock) - started) * 1000
    except ValueError:
        return 0.0
    if not math.isfinite(duration_ms) or duration_ms < 0:
        return 0.0
    return duration_ms


def _build_debug_answer_url(api_url: str) -> str:
    parsed = urlsplit(api_url)
    base_path = parsed.path.rstrip("/")
    return urlunsplit(
        (
            parsed.scheme,
            parsed.netloc,
            f"{base_path}{_DEBUG_ANSWER_PATH}",
            "",
            "",
        )
    )

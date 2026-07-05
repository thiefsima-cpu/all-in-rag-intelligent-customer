"""Debug answer client and observation normalization for the live quality gate."""

from __future__ import annotations

from time import perf_counter
from typing import Any, Protocol
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


_REQUEST_FAILED_CODE = "LIVE_QUALITY_REQUEST_FAILED"
_DEBUG_ANSWER_PATH = "/v1/debug/answers"
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
_REQUIRED_ROUTE_TRACE_FIELDS = frozenset({"strategy", "stages", "fallbacks", "diagnostics"})
_REQUIRED_ROUTE_STAGE_FIELDS = frozenset({"sources"})
_REQUIRED_ROUTE_DIAGNOSTIC_FIELDS = frozenset(
    {"used_fallback", "fallback_count", "retrieval_degraded"}
)
_REQUIRED_GENERATION_TRACE_FIELDS = frozenset(
    {"fallback_used", "total_tokens", "estimated_cost_usd"}
)


def normalize_live_quality_observation(
    case: LiveQualityCasePolicy,
    payload: dict[str, Any],
) -> LiveQualityObservation:
    response = AnswerResponseModel.model_validate(payload)
    _require_explicit_live_quality_contract(response)

    answer = response.response
    summary = answer.summary
    public_diagnostics = answer.diagnostics.diagnostics
    route_trace = answer.traces.route_trace
    route_diagnostics = route_trace.diagnostics
    generation_trace = answer.traces.generation_trace

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
        latency_ms=summary.latency_ms,
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
) -> LiveQualityCaseRunResult:
    started = perf_counter()
    session = http_session if http_session is not None else requests.Session()
    owns_session = http_session is None

    try:
        payload = _post_debug_answer(
            settings=settings,
            policy=policy,
            case=case,
            session=session,
            request_id_factory=request_id_factory,
        )
        observation = normalize_live_quality_observation(case, payload)
    except (requests.RequestException, OSError, ValueError, ValidationError):
        duration_ms = (perf_counter() - started) * 1000
        return LiveQualityCaseRunResult(
            case_id=case.case_id,
            observation=None,
            checks=(
                GateCheckResult.fail_check(
                    "live_quality_debug_answer_request",
                    failure_type=GateFailureType.DEPENDENCY_UNAVAILABLE,
                    code=_REQUEST_FAILED_CODE,
                    expected={"endpoint": "/v1/debug/answers"},
                    actual={"case_id": case.case_id, "result": "request_failed"},
                    duration_ms=duration_ms,
                ),
            ),
        )
    finally:
        if owns_session:
            session.close()

    return LiveQualityCaseRunResult(case_id=case.case_id, observation=observation, checks=())


def _post_debug_answer(
    *,
    settings: LiveQualityGateSettings,
    policy: LiveQualityGatePolicy,
    case: LiveQualityCasePolicy,
    session: requests.Session,
    request_id_factory: RequestIdFactory | None,
) -> dict[str, Any]:
    request_id = request_id_factory() if request_id_factory is not None else uuid4()
    headers = {"X-Request-ID": f"live-quality-gate-{request_id}"}
    if settings.api_token:
        headers["Authorization"] = f"Bearer {settings.api_token}"

    response = session.post(
        _build_debug_answer_url(settings.api_url),
        json={
            "question": case.query,
            "stream": False,
            "explain_routing": True,
        },
        headers=headers,
        timeout=policy.timeouts.request_seconds,
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError("live quality debug answer response must be a JSON object")
    return payload


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

"""Live debug-answer client and normalization for the integration gate."""

from __future__ import annotations

from time import perf_counter
from typing import Any, Protocol
from uuid import uuid4

import requests
from pydantic import ValidationError

from rag_modules.interfaces.api.answer_models import AnswerResponseModel
from scripts.gates import GateCheckResult, GateFailureType

from .evaluator import evaluate_live_case
from .models import (
    IntegrationGatePolicy,
    IntegrationGateSettings,
    LiveCaseObservation,
    LiveCasePolicy,
    LiveCaseRunResult,
)


class RequestIdFactory(Protocol):
    def __call__(self) -> object: ...


def normalize_live_case_observation(
    case: LiveCasePolicy,
    response: AnswerResponseModel,
) -> LiveCaseObservation:
    """Extract stable evaluation signals from a debug answer API response."""

    payload = response.response
    summary = payload.summary
    route_trace = payload.traces.route_trace
    generation_trace = payload.traces.generation_trace
    route_diagnostics = route_trace.diagnostics

    evidence_documents = payload.grounding.evidence_documents
    evidence_sources = {document.source for document in evidence_documents if document.source}
    stage_sources = {
        source
        for stage in route_trace.stages.values()
        for source, count in stage.sources.items()
        if count > 0
    }

    fallback_used = (
        summary.fallback_used
        or route_diagnostics.used_fallback
        or route_diagnostics.fallback_count > 0
        or bool(route_trace.fallbacks)
        or generation_trace.fallback_used
    )
    retrieval_degraded = (
        payload.diagnostics.diagnostics.retrieval_degraded or route_diagnostics.retrieval_degraded
    )
    generation_cost = generation_trace.estimated_cost_usd
    estimated_cost_usd = generation_cost if generation_cost > 0 else summary.estimated_cost_usd

    return LiveCaseObservation(
        case_id=case.case_id,
        strategy=summary.strategy or route_trace.strategy,
        sources=frozenset(evidence_sources | stage_sources),
        evidence_count=len(evidence_documents),
        fallback_used=fallback_used,
        retrieval_degraded=retrieval_degraded,
        latency_ms=summary.latency_ms,
        total_tokens=generation_trace.total_tokens,
        estimated_cost_usd=estimated_cost_usd,
    )


def run_live_case(
    settings: IntegrationGateSettings,
    policy: IntegrationGatePolicy,
    case: LiveCasePolicy,
    http_session: requests.Session | None = None,
    request_id_factory: RequestIdFactory | None = None,
) -> LiveCaseRunResult:
    """Execute one live debug-answer case and evaluate the normalized response."""

    start_time = perf_counter()
    owns_session = http_session is None
    session = http_session if http_session is not None else requests.Session()
    try:
        payload = _post_debug_answer(
            settings=settings,
            policy=policy,
            case=case,
            http_session=session,
            request_id_factory=request_id_factory or uuid4,
        )
    except Exception:
        return LiveCaseRunResult(
            case_id=case.case_id,
            observation=None,
            checks=(
                _request_failed_check(
                    case.case_id,
                    code="SERVING_API_REQUEST_FAILED",
                    failure_type=GateFailureType.DEPENDENCY_UNAVAILABLE,
                    start_time=start_time,
                ),
            ),
        )
    finally:
        if owns_session:
            _close_quietly(session)

    try:
        response_model = AnswerResponseModel.model_validate(payload)
    except ValidationError:
        return LiveCaseRunResult(
            case_id=case.case_id,
            observation=None,
            checks=(
                _request_failed_check(
                    case.case_id,
                    code="API_RESPONSE_CONTRACT_INVALID",
                    failure_type=GateFailureType.CONTRACT_REGRESSION,
                    start_time=start_time,
                ),
            ),
        )

    observation = normalize_live_case_observation(case, response_model)
    return LiveCaseRunResult(
        case_id=case.case_id,
        observation=observation,
        checks=evaluate_live_case(case, observation),
    )


def _post_debug_answer(
    *,
    settings: IntegrationGateSettings,
    policy: IntegrationGatePolicy,
    case: LiveCasePolicy,
    http_session: requests.Session,
    request_id_factory: RequestIdFactory,
) -> Any:
    headers = {
        "X-Request-ID": f"integration-gate-{request_id_factory()}",
    }
    if settings.api_token:
        headers["Authorization"] = f"Bearer {settings.api_token}"

    response = http_session.post(
        f"{settings.api_url.rstrip('/')}/v1/debug/answers",
        json={
            "question": case.question,
            "stream": False,
            "explain_routing": True,
        },
        headers=headers,
        timeout=min(case.timeout_seconds, policy.timeouts.request_seconds),
    )
    response.raise_for_status()
    return response.json()


def _request_failed_check(
    case_id: str,
    *,
    code: str,
    failure_type: GateFailureType,
    start_time: float,
) -> GateCheckResult:
    return GateCheckResult.fail_check(
        f"case.{case_id}.request",
        failure_type=failure_type,
        code=code,
        expected=True,
        actual=False,
        duration_ms=_elapsed_ms(start_time),
    )


def _elapsed_ms(start_time: float) -> float:
    return (perf_counter() - start_time) * 1000


def _close_quietly(resource: object | None) -> None:
    close = getattr(resource, "close", None)
    if callable(close):
        try:
            close()
        except Exception:
            pass

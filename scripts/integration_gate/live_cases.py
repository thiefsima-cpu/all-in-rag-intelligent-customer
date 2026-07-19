"""Live debug-answer client and normalization for the integration gate."""

from __future__ import annotations

import re
from time import perf_counter
from typing import Any, Protocol
from unicodedata import normalize
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

_REQUIRED_PAYLOAD_FIELDS = frozenset({"summary", "grounding", "diagnostics", "traces"})
_REQUIRED_SUMMARY_FIELDS = frozenset(
    {"strategy", "latency_ms", "fallback_used", "estimated_cost_usd"}
)
_REQUIRED_GROUNDING_FIELDS = frozenset({"evidence_documents"})
_REQUIRED_DIAGNOSTICS_FIELDS = frozenset({"diagnostics"})
_REQUIRED_QUERY_DIAGNOSTIC_FIELDS = frozenset({"retrieval_degraded"})
_REQUIRED_TRACE_FIELDS = frozenset({"route_trace", "generation_trace"})
_REQUIRED_ROUTE_TRACE_FIELDS = frozenset({"strategy", "stages", "fallbacks", "diagnostics"})
_REQUIRED_ROUTE_DIAGNOSTIC_FIELDS = frozenset(
    {"used_fallback", "fallback_count", "retrieval_degraded"}
)
_REQUIRED_GENERATION_TRACE_FIELDS = frozenset(
    {"total_tokens", "estimated_cost_usd", "fallback_used"}
)
_CHINESE_DIGITS = {
    "零": 0,
    "〇": 0,
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
}
_CHINESE_QUANTITY_PATTERN = re.compile(
    r"([零〇一二两三四五六七八九十]+)(天|年|个月|月|日|小时|分钟|周)"
)
_NEGATED_FACT_PREFIXES = (
    "不支持",
    "不提供",
    "不能",
    "无法",
    "未",
    "没有",
    "并非",
    "不是",
)
_NEGATED_FACT_SUFFIXES = (
    "不适用",
    "不支持",
    "不存在",
    "无效",
    "不可",
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
    observed_entity_ids = {
        _normalized_match_text(document.entity_id or document.recipe_id)
        for document in evidence_documents
        if document.entity_id or document.recipe_id
    }
    expected_entity_ids = {
        _normalized_match_text(entity_id) for entity_id in case.expected_entity_ids
    }
    normalized_answer = _normalized_match_text(summary.answer)
    matched_fact_count = sum(
        _required_fact_is_asserted(normalized_answer, _normalized_match_text(fact))
        for fact in case.must_include_facts
    )

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
        expected_entity_count=len(expected_entity_ids),
        matched_expected_entity_count=len(expected_entity_ids & observed_entity_ids),
        expected_fact_count=len(case.must_include_facts),
        matched_expected_fact_count=matched_fact_count,
    )


def _normalized_match_text(value: object) -> str:
    normalized = "".join(normalize("NFKC", str(value or "")).casefold().split())
    return _CHINESE_QUANTITY_PATTERN.sub(_replace_chinese_quantity, normalized)


def _required_fact_is_asserted(answer: str, fact: str) -> bool:
    if not answer or not fact:
        return False
    for match in re.finditer(re.escape(fact), answer):
        start, end = match.span()
        if fact[0].isdigit() and start > 0 and answer[start - 1].isdigit():
            continue
        if fact.isdigit() and end < len(answer) and answer[end].isdigit():
            continue
        prefix = answer[max(0, start - 8) : start]
        suffix = answer[end : min(len(answer), end + 12)]
        if any(marker in prefix for marker in _NEGATED_FACT_PREFIXES):
            continue
        if any(marker in suffix for marker in _NEGATED_FACT_SUFFIXES):
            continue
        return True
    return False


def _replace_chinese_quantity(match: re.Match[str]) -> str:
    number = _parse_chinese_number(match.group(1))
    if number is None:
        return match.group(0)
    return f"{number}{match.group(2)}"


def _parse_chinese_number(value: str) -> int | None:
    if "十" not in value:
        digits = [_CHINESE_DIGITS.get(character) for character in value]
        if any(digit is None for digit in digits):
            return None
        return int("".join(str(digit) for digit in digits))
    if value.count("十") != 1:
        return None
    tens_text, ones_text = value.split("十")
    tens = 1 if not tens_text else _CHINESE_DIGITS.get(tens_text)
    ones = 0 if not ones_text else _CHINESE_DIGITS.get(ones_text)
    if tens is None or ones is None:
        return None
    return tens * 10 + ones


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

    if not _has_required_debug_response_contract(response_model):
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


def _has_required_debug_response_contract(response: AnswerResponseModel) -> bool:
    payload = response.response
    traces = payload.traces
    route_trace = traces.route_trace
    generation_trace = traces.generation_trace

    return (
        _fields_were_explicitly_set(payload, _REQUIRED_PAYLOAD_FIELDS)
        and _fields_were_explicitly_set(payload.summary, _REQUIRED_SUMMARY_FIELDS)
        and _fields_were_explicitly_set(payload.grounding, _REQUIRED_GROUNDING_FIELDS)
        and _fields_were_explicitly_set(payload.diagnostics, _REQUIRED_DIAGNOSTICS_FIELDS)
        and _fields_were_explicitly_set(
            payload.diagnostics.diagnostics,
            _REQUIRED_QUERY_DIAGNOSTIC_FIELDS,
        )
        and _fields_were_explicitly_set(traces, _REQUIRED_TRACE_FIELDS)
        and _fields_were_explicitly_set(route_trace, _REQUIRED_ROUTE_TRACE_FIELDS)
        and _fields_were_explicitly_set(
            route_trace.diagnostics,
            _REQUIRED_ROUTE_DIAGNOSTIC_FIELDS,
        )
        and _fields_were_explicitly_set(generation_trace, _REQUIRED_GENERATION_TRACE_FIELDS)
    )


def _fields_were_explicitly_set(model: object, required_fields: frozenset[str]) -> bool:
    fields_set = getattr(model, "model_fields_set", frozenset())
    return required_fields <= fields_set


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

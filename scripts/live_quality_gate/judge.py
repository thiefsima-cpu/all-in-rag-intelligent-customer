"""Independent LLM judge client for live quality gate observations."""

from __future__ import annotations

import json
from collections.abc import Sequence
from numbers import Real
from typing import Any, Protocol

import requests

from scripts.gates import GateCheckResult, GateFailureType

from .models import JudgeSettings, LiveQualityCasePolicy
from .runtime_models import JudgeRunResult, JudgeVerdict, LiveQualityObservation

_JUDGE_SYSTEM_PROMPT = (
    "You are an independent RAG quality judge. Evaluate only the provided packet. "
    "Return valid JSON only: one object with case_id (string), scores (an object containing "
    "every requested score as a number from 0 to 1), passed (boolean), and rationale "
    "(non-empty string). Do not use Markdown fences or add other fields outside the JSON object."
)
_MAX_EVIDENCE_ITEMS = 6
_MAX_SNIPPET_CHARS = 1_800


class JudgeHttpSession(Protocol):
    def post(
        self,
        url: str,
        *,
        json: dict[str, Any],
        headers: dict[str, str],
        timeout: float,
    ) -> Any: ...

    def close(self) -> None: ...


def build_judge_packet(
    case: LiveQualityCasePolicy,
    observation: LiveQualityObservation,
) -> dict[str, Any]:
    return {
        "case_id": case.case_id,
        "query": case.query,
        "expected_response_mode": case.expected_response_mode.value,
        "answer": observation.answer,
        "evidence": [
            {
                "entity_name": item.entity_name,
                "source": item.source,
                "snippet": item.content[:_MAX_SNIPPET_CHARS],
            }
            for item in observation.evidence[:_MAX_EVIDENCE_ITEMS]
        ],
        "must_include_facts": list(case.must_include_facts),
        "must_not_claim": list(case.must_not_claim),
        "judge_rubric": dict(case.judge_rubric),
    }


def run_judge(
    *,
    settings: JudgeSettings,
    case: LiveQualityCasePolicy,
    observation: LiveQualityObservation,
    expected_score_names: Sequence[str],
    minimum_score: float,
    http_session: JudgeHttpSession | None = None,
) -> JudgeRunResult:
    session = http_session if http_session is not None else requests.Session()
    owns_session = http_session is None

    try:
        content = _request_judge_content(
            settings=settings,
            case=case,
            observation=observation,
            expected_score_names=tuple(expected_score_names),
            session=session,
        )
    except (requests.RequestException, OSError, ValueError, TypeError, KeyError, IndexError):
        return _failed_judge_result(
            case.case_id,
            code="JUDGE_REQUEST_FAILED",
            actual_result="request_failed",
        )
    finally:
        if owns_session:
            session.close()

    try:
        verdict = _parse_verdict(
            content,
            expected_case_id=case.case_id,
            expected_score_names=tuple(expected_score_names),
        )
    except (json.JSONDecodeError, ValueError, TypeError):
        return _failed_judge_result(
            case.case_id,
            code="JUDGE_RESPONSE_INVALID",
            actual_result="invalid_response",
        )

    scores = dict(verdict.scores)
    score_passed = all(scores[name] >= minimum_score for name in expected_score_names)
    passed = verdict.passed and score_passed
    check = (
        GateCheckResult.pass_check(
            f"case.{case.case_id}.judge",
            code="JUDGE_QUALITY_OK",
            expected={"minimum_score": minimum_score},
            actual=scores,
        )
        if passed
        else GateCheckResult.fail_check(
            f"case.{case.case_id}.judge",
            failure_type=GateFailureType.QUALITY_REGRESSION,
            code="JUDGE_QUALITY_FAILED",
            expected={"minimum_score": minimum_score},
            actual=scores,
        )
    )
    return JudgeRunResult(case_id=case.case_id, verdict=verdict, checks=(check,))


def _request_judge_content(
    *,
    settings: JudgeSettings,
    case: LiveQualityCasePolicy,
    observation: LiveQualityObservation,
    expected_score_names: tuple[str, ...],
    session: JudgeHttpSession,
) -> str:
    packet = build_judge_packet(case, observation)
    request_payload: dict[str, Any] = {
        "model": settings.model,
        "messages": [
            {"role": "system", "content": _JUDGE_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "packet": packet,
                        "expected_score_names": list(expected_score_names),
                    },
                    ensure_ascii=False,
                    allow_nan=False,
                ),
            },
        ],
        "temperature": 0,
        "response_format": {"type": "json_object"},
    }
    if settings.enable_thinking is not None:
        request_payload["enable_thinking"] = settings.enable_thinking
    response = session.post(
        settings.api_url,
        json=request_payload,
        headers={"Authorization": f"Bearer {settings.api_key}"},
        timeout=settings.timeout_seconds,
    )
    response.raise_for_status()
    return _extract_content(response.json())


def _extract_content(payload: Any) -> str:
    if not isinstance(payload, dict):
        raise ValueError("judge response envelope must be a JSON object")
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ValueError("judge response envelope must include choices")
    first_choice = choices[0]
    if not isinstance(first_choice, dict):
        raise ValueError("judge response choice must be an object")
    message = first_choice.get("message")
    if not isinstance(message, dict):
        raise ValueError("judge response message must be an object")
    content = message.get("content")
    if not isinstance(content, str) or not content.strip():
        raise ValueError("judge response content must be non-empty text")
    return content


def _parse_verdict(
    content: str,
    *,
    expected_case_id: str,
    expected_score_names: tuple[str, ...],
) -> JudgeVerdict:
    payload = json.loads(content)
    if not isinstance(payload, dict):
        raise ValueError("judge verdict must be a JSON object")
    if payload.get("case_id") != expected_case_id:
        raise ValueError("judge verdict case_id mismatch")

    scores = payload.get("scores")
    if not isinstance(scores, dict):
        raise ValueError("judge verdict scores must be an object")

    parsed_scores: dict[str, float] = {}
    for name in expected_score_names:
        value = scores.get(name)
        if isinstance(value, bool) or not isinstance(value, Real):
            raise ValueError("judge verdict score must be numeric")
        number = float(value)
        if not 0.0 <= number <= 1.0:
            raise ValueError("judge verdict score must be between zero and one")
        parsed_scores[name] = number

    passed = payload.get("passed")
    if not isinstance(passed, bool):
        raise ValueError("judge verdict passed must be boolean")

    rationale = payload.get("rationale")
    if not isinstance(rationale, str) or not rationale.strip():
        raise ValueError("judge verdict rationale must be non-empty")

    return JudgeVerdict(
        case_id=expected_case_id,
        scores=parsed_scores,
        passed=passed,
        rationale=rationale.strip(),
    )


def _failed_judge_result(
    case_id: str,
    *,
    code: str,
    actual_result: str,
) -> JudgeRunResult:
    return JudgeRunResult(
        case_id=case_id,
        verdict=None,
        checks=(
            GateCheckResult.fail_check(
                f"case.{case_id}.judge",
                failure_type=GateFailureType.JUDGE_UNAVAILABLE,
                code=code,
                expected={"judge_response": "valid_json_verdict"},
                actual={"case_id": case_id, "result": actual_result},
            ),
        ),
    )

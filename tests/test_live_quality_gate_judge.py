from __future__ import annotations

import json
from dataclasses import replace
from typing import Any

import pytest
import requests

from scripts.gates import GateFailureType
from scripts.live_quality_gate.judge import build_judge_packet, run_judge
from scripts.live_quality_gate.models import JudgeSettings
from scripts.live_quality_gate.runtime_models import JudgeVerdict
from tests.test_live_quality_gate_client import case, settings
from tests.test_live_quality_gate_evaluator import make_observation


class FakeJudgeResponse:
    def __init__(self, content: str, error: Exception | None = None) -> None:
        self.content = content
        self.error = error

    def raise_for_status(self) -> None:
        if self.error is not None:
            raise self.error

    def json(self) -> dict[str, Any]:
        return {"choices": [{"message": {"content": self.content}}]}


class FakeJudgeSession:
    def __init__(self, response: FakeJudgeResponse) -> None:
        self.response = response
        self.posts: list[dict[str, Any]] = []
        self.closed = False

    def post(
        self,
        url: str,
        *,
        json: dict[str, Any],
        headers: dict[str, str],
        timeout: float,
    ) -> FakeJudgeResponse:
        self.posts.append({"url": url, "json": json, "headers": headers, "timeout": timeout})
        return self.response

    def close(self) -> None:
        self.closed = True


def verdict_payload(
    *,
    case_id: str = "grounded_mapo_tofu",
    passed: bool = True,
    scores: dict[str, Any] | None = None,
    rationale: str = "The answer is grounded in the evidence.",
) -> str:
    return json.dumps(
        {
            "case_id": case_id,
            "scores": (
                {"faithfulness": 1.0, "answer_relevance": 0.9} if scores is None else scores
            ),
            "passed": passed,
            "rationale": rationale,
        }
    )


def run_default_judge(http: FakeJudgeSession, *, minimum_score: float = 0.8):
    return run_judge(
        settings=settings().judge,
        case=case(),
        observation=make_observation(),
        expected_score_names=("faithfulness", "answer_relevance"),
        minimum_score=minimum_score,
        http_session=http,
    )


def test_build_judge_packet_contains_redacted_evidence_summary() -> None:
    observation = make_observation()
    packet = build_judge_packet(case(), observation)

    assert packet["case_id"] == "grounded_mapo_tofu"
    assert packet["query"] == "How do I make mapo tofu?"
    assert packet["expected_response_mode"] == "grounded_answer"
    assert packet["answer"] == "Use doubanjiang with tofu for mapo tofu."
    assert packet["evidence"] == [
        {
            "entity_name": "Mapo Tofu",
            "source": "vector",
            "snippet": "Mapo tofu uses doubanjiang and tofu.",
        }
    ]
    assert packet["must_include_facts"] == ["tofu"]
    assert packet["must_not_claim"] == ["palace secret recipe"]
    assert packet["judge_rubric"] == case().judge_rubric

    serialized = json.dumps(packet, ensure_ascii=False)
    assert "Authorization" not in serialized
    assert "judge-key" not in serialized
    assert "serving-token" not in serialized


def test_build_judge_packet_limits_evidence_items_and_snippet_length() -> None:
    evidence = make_observation().evidence[0]
    observation = make_observation(
        evidence=tuple(
            type(evidence)(
                entity_name=f"Recipe {index}",
                source="vector",
                content=("x" * 300),
                score=0.9,
            )
            for index in range(8)
        )
    )

    packet = build_judge_packet(case(), observation)

    assert len(packet["evidence"]) == 6
    assert packet["evidence"][0]["entity_name"] == "Recipe 0"
    assert len(packet["evidence"][0]["snippet"]) == 300


def test_run_judge_posts_openai_compatible_request_and_parses_verdict() -> None:
    http = FakeJudgeSession(FakeJudgeResponse(verdict_payload()))

    result = run_default_judge(http)

    assert isinstance(result.verdict, JudgeVerdict)
    assert result.verdict.passed is True
    assert result.verdict.scores == {"faithfulness": 1.0, "answer_relevance": 0.9}
    assert result.checks[0].code == "JUDGE_QUALITY_OK"
    assert result.checks[0].passed is True
    assert http.posts[0]["url"] == "https://judge.example.com/v1/chat/completions"
    assert http.posts[0]["headers"] == {"Authorization": "Bearer judge-key"}
    assert http.posts[0]["json"]["model"] == "judge.model-v1"
    assert http.posts[0]["json"]["temperature"] == 0
    assert http.posts[0]["json"]["response_format"] == {"type": "json_object"}
    assert http.posts[0]["timeout"] == 45.0
    assert http.closed is False


def test_run_judge_forwards_explicit_thinking_mode() -> None:
    http = FakeJudgeSession(FakeJudgeResponse(verdict_payload()))

    result = run_judge(
        settings=replace(settings().judge, enable_thinking=False),
        case=case(),
        observation=make_observation(),
        expected_score_names=("faithfulness", "answer_relevance"),
        minimum_score=0.8,
        http_session=http,
    )

    assert result.verdict is not None
    assert http.posts[0]["json"]["enable_thinking"] is False


def test_judge_verdict_copies_and_freezes_scores() -> None:
    source_scores = {"faithfulness": 1.0, "answer_relevance": 0.9}
    verdict = JudgeVerdict(
        case_id="grounded_mapo_tofu",
        scores=source_scores,
        passed=True,
        rationale="grounded",
    )
    source_scores["faithfulness"] = 0.0

    assert verdict.scores == {"faithfulness": 1.0, "answer_relevance": 0.9}
    with pytest.raises(TypeError):
        verdict.scores["faithfulness"] = 0.1


def test_run_judge_rejects_mismatched_case_id_as_judge_unavailable() -> None:
    http = FakeJudgeSession(FakeJudgeResponse(verdict_payload(case_id="wrong_case")))

    result = run_default_judge(http)

    assert result.verdict is None
    assert result.checks[0].code == "JUDGE_RESPONSE_INVALID"
    assert result.checks[0].failure_type is GateFailureType.JUDGE_UNAVAILABLE


def test_valid_failing_verdict_is_quality_regression() -> None:
    http = FakeJudgeSession(FakeJudgeResponse(verdict_payload(passed=False)))

    result = run_default_judge(http)

    assert result.verdict is not None
    assert result.checks[0].code == "JUDGE_QUALITY_FAILED"
    assert result.checks[0].failure_type is GateFailureType.QUALITY_REGRESSION


def test_minimum_score_failure_is_quality_regression() -> None:
    http = FakeJudgeSession(
        FakeJudgeResponse(verdict_payload(scores={"faithfulness": 1.0, "answer_relevance": 0.79}))
    )

    result = run_default_judge(http, minimum_score=0.8)

    assert result.verdict is not None
    assert result.verdict.passed is True
    assert result.checks[0].code == "JUDGE_QUALITY_FAILED"
    assert result.checks[0].failure_type is GateFailureType.QUALITY_REGRESSION


@pytest.mark.parametrize(
    "content",
    [
        "{not-json",
        verdict_payload(scores={"faithfulness": 1.0}),
        verdict_payload(scores={"faithfulness": 1.0, "answer_relevance": "high"}),
        verdict_payload(scores={"faithfulness": 1.0, "answer_relevance": 1.01}),
        verdict_payload(rationale=" "),
    ],
)
def test_invalid_judge_content_is_judge_unavailable(content: str) -> None:
    http = FakeJudgeSession(FakeJudgeResponse(content))

    result = run_default_judge(http)

    assert result.verdict is None
    assert result.checks[0].code == "JUDGE_RESPONSE_INVALID"
    assert result.checks[0].failure_type is GateFailureType.JUDGE_UNAVAILABLE


def test_judge_transport_failure_does_not_leak_secret_details() -> None:
    http = FakeJudgeSession(
        FakeJudgeResponse("{}", error=requests.Timeout("judge-key leaked detail"))
    )

    result = run_judge(
        settings=JudgeSettings(
            api_url="https://judge.example.com/v1/chat/completions",
            api_key="judge-key",
            model="judge.model-v1",
            timeout_seconds=30.0,
        ),
        case=case(),
        observation=make_observation(),
        expected_score_names=("faithfulness", "answer_relevance"),
        minimum_score=0.8,
        http_session=http,
    )

    assert result.verdict is None
    assert result.checks[0].code == "JUDGE_REQUEST_FAILED"
    assert result.checks[0].failure_type is GateFailureType.JUDGE_UNAVAILABLE

    rendered = repr(result.checks[0].to_dict()) + repr(result.checks[0])
    assert "judge-key" not in rendered
    assert "leaked detail" not in rendered

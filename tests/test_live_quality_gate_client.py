from __future__ import annotations

from copy import deepcopy
from typing import Any

import pytest
import requests

from scripts.gates import GateFailureType
from scripts.live_quality_gate.client import (
    normalize_live_quality_observation,
    run_live_case,
)
from scripts.live_quality_gate.models import (
    JudgeSettings,
    LiveQualityCasePolicy,
    LiveQualityGatePolicy,
    LiveQualityGateSettings,
    LiveQualityJudgePolicy,
    LiveQualityResponseMode,
    LiveQualitySliceThresholds,
    LiveQualityThresholds,
    LiveQualityTimeouts,
    ManualReviewPolicy,
    RequiredSliceCoverage,
)
from scripts.live_quality_gate.runtime_models import (
    LiveQualityCaseRunResult,
    LiveQualityEvidence,
    LiveQualityObservation,
)


class FakeResponse:
    def __init__(
        self,
        payload: Any = None,
        error: Exception | None = None,
    ) -> None:
        self.payload = {} if payload is None else payload
        self.error = error

    def raise_for_status(self) -> None:
        if self.error is not None:
            raise self.error

    def json(self) -> Any:
        return self.payload


class FakeSession:
    def __init__(self, response: FakeResponse) -> None:
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
    ) -> FakeResponse:
        self.posts.append({"url": url, "json": json, "headers": headers, "timeout": timeout})
        return self.response

    def close(self) -> None:
        self.closed = True


def settings(
    api_token: str | None = "serving-token",
    api_url: str = "https://serving.example.com/api",
) -> LiveQualityGateSettings:
    return LiveQualityGateSettings(
        api_url=api_url,
        api_token=api_token,
        judge=JudgeSettings(
            api_url="https://judge.example.com/v1/chat/completions",
            api_key="judge-key",
            model="judge.model-v1",
            timeout_seconds=45.0,
        ),
    )


def case() -> LiveQualityCasePolicy:
    return LiveQualityCasePolicy(
        case_id="grounded_mapo_tofu",
        query="How do I make mapo tofu?",
        query_type="single_recipe",
        cuisine="sichuan",
        constraint_types=[],
        risk_tags=[],
        expected_response_mode=LiveQualityResponseMode.GROUNDED_ANSWER,
        allowed_strategies=["hybrid_traditional", "combined"],
        required_sources=["vector"],
        relevant_recipes={"Mapo Tofu": 3.0},
        must_include_facts=["tofu"],
        must_not_claim=["palace secret recipe"],
        judge_rubric={
            "faithfulness": "Use only the provided evidence.",
            "answer_relevance": "Answer the user's recipe question.",
        },
        manual_review=ManualReviewPolicy(owner="business-quality", sample=True),
    )


def policy() -> LiveQualityGatePolicy:
    return LiveQualityGatePolicy(
        schema_version=1,
        top_k=6,
        timeouts=LiveQualityTimeouts(request_seconds=12.5, judge_seconds=45.0),
        judge=LiveQualityJudgePolicy(
            required=True,
            score_names=["faithfulness", "answer_relevance"],
            minimum_score=0.8,
        ),
        thresholds=LiveQualityThresholds(
            minimum_case_count=1,
            minimum_pass_rate=0.9,
            minimum_deterministic_pass_rate=0.9,
            minimum_judge_pass_rate=0.9,
            minimum_recall_at_k=0.7,
            minimum_mrr=0.6,
            minimum_ndcg_at_k=0.7,
            maximum_fallback_rate=0.0,
            maximum_retrieval_degradation_rate=0.0,
            maximum_p95_latency_ms=60000.0,
            maximum_estimated_cost_usd=1.0,
        ),
        required_slice_coverage=RequiredSliceCoverage(),
        slice_thresholds=LiveQualitySliceThresholds(),
        cases=[case()],
    )


def answer_payload() -> dict[str, Any]:
    return {
        "response": {
            "summary": {
                "answer": "Use tofu, doubanjiang, and Sichuan peppercorns.",
                "strategy": "combined",
                "latency_ms": 321.5,
                "fallback_used": False,
                "prompt_tokens": 101,
                "completion_tokens": 37,
                "total_tokens": 138,
                "estimated_cost_usd": 0.0042,
            },
            "grounding": {
                "evidence_documents": [
                    {
                        "recipe_name": "Mapo Tofu",
                        "source": "vector",
                        "content": "Mapo tofu uses tofu and doubanjiang.",
                        "score": 0.98,
                    },
                    {
                        "recipe_name": "Dan Dan Noodles",
                        "source": "graph",
                        "content": "Sichuan peppercorns are common in Sichuan dishes.",
                        "score": 0.61,
                    },
                    {
                        "recipe_name": "Mapo Tofu",
                        "source": "vector",
                        "content": "Serve mapo tofu hot.",
                        "score": 0.52,
                    },
                ],
            },
            "diagnostics": {"diagnostics": {"retrieval_degraded": False}},
            "traces": {
                "route_trace": {
                    "strategy": "combined",
                    "stages": {
                        "hybrid": {"sources": {"vector": 2}},
                        "post_process": {"sources": {"rerank": 1}},
                        "empty": {"sources": {"zero_count": 0}},
                    },
                    "fallbacks": ["planner_timeout"],
                    "diagnostics": {
                        "used_fallback": False,
                        "fallback_count": 0,
                        "retrieval_degraded": True,
                    },
                },
                "generation_trace": {
                    "fallback_used": False,
                    "prompt_tokens": 202,
                    "completion_tokens": 74,
                    "total_tokens": 276,
                    "estimated_cost_usd": 0.0084,
                },
            },
        }
    }


def delete_nested_key(payload: dict[str, Any], *path: str) -> dict[str, Any]:
    mutated = deepcopy(payload)
    cursor: dict[str, Any] = mutated
    for key in path[:-1]:
        cursor = cursor[key]
    del cursor[path[-1]]
    return mutated


def assert_sanitized_request_failed_result(
    result: LiveQualityCaseRunResult,
    *,
    expected_duration_ms: float,
    secrets: tuple[str, ...],
) -> None:
    assert result.observation is None
    assert len(result.checks) == 1
    check = result.checks[0]
    assert check.code == "LIVE_QUALITY_REQUEST_FAILED"
    assert check.failure_type is GateFailureType.DEPENDENCY_UNAVAILABLE
    assert check.duration_ms == pytest.approx(expected_duration_ms)

    sanitized_repr = repr(check.to_dict())
    check_repr = repr(check)
    for secret in secrets:
        assert secret not in sanitized_repr
        assert secret not in check_repr


def test_normalize_live_quality_observation_extracts_answer_metrics_and_diagnostics() -> None:
    observation = normalize_live_quality_observation(case(), answer_payload())

    assert observation == LiveQualityObservation(
        case_id="grounded_mapo_tofu",
        answer="Use tofu, doubanjiang, and Sichuan peppercorns.",
        strategy="combined",
        evidence=(
            LiveQualityEvidence(
                recipe_name="Mapo Tofu",
                source="vector",
                content="Mapo tofu uses tofu and doubanjiang.",
                score=0.98,
            ),
            LiveQualityEvidence(
                recipe_name="Dan Dan Noodles",
                source="graph",
                content="Sichuan peppercorns are common in Sichuan dishes.",
                score=0.61,
            ),
            LiveQualityEvidence(
                recipe_name="Mapo Tofu",
                source="vector",
                content="Serve mapo tofu hot.",
                score=0.52,
            ),
        ),
        ranked_recipe_names=("Mapo Tofu", "Dan Dan Noodles", "Mapo Tofu"),
        sources=frozenset({"vector", "graph", "rerank"}),
        fallback_used=True,
        retrieval_degraded=True,
        latency_ms=321.5,
        prompt_tokens=101,
        completion_tokens=37,
        total_tokens=276,
        estimated_cost_usd=0.0084,
    )


def test_normalize_live_quality_observation_preserves_duplicate_ranked_recipes() -> None:
    observation = normalize_live_quality_observation(case(), answer_payload())

    assert observation.ranked_recipe_names == ("Mapo Tofu", "Dan Dan Noodles", "Mapo Tofu")


def test_normalize_live_quality_observation_ignores_zero_count_stage_sources() -> None:
    payload = answer_payload()
    payload["response"]["traces"]["route_trace"]["stages"] = {
        "empty": {"sources": {"zero_count": 0, "negative_count": -1}},
        "filled": {"sources": {"vector": 2}},
    }

    observation = normalize_live_quality_observation(case(), payload)

    assert observation.sources == frozenset({"vector", "graph"})


def test_normalize_live_quality_observation_ignores_empty_stage_source_keys() -> None:
    payload = answer_payload()
    payload["response"]["traces"]["route_trace"]["stages"] = {
        "filled": {"sources": {"": 1, "vector": 2}},
    }

    observation = normalize_live_quality_observation(case(), payload)

    assert observation.sources == frozenset({"vector", "graph"})
    assert "" not in observation.sources


def test_normalize_live_quality_observation_falls_back_to_route_strategy() -> None:
    payload = answer_payload()
    payload["response"]["summary"]["strategy"] = ""
    payload["response"]["traces"]["route_trace"]["strategy"] = "graph_rag"

    observation = normalize_live_quality_observation(case(), payload)

    assert observation.strategy == "graph_rag"


def test_normalize_live_quality_observation_prefers_generation_total_tokens_and_cost() -> None:
    observation = normalize_live_quality_observation(case(), answer_payload())

    assert observation.prompt_tokens == 101
    assert observation.completion_tokens == 37
    assert observation.total_tokens == 276
    assert observation.estimated_cost_usd == 0.0084


def test_normalize_live_quality_observation_falls_back_to_summary_total_tokens_and_cost() -> None:
    payload = answer_payload()
    payload["response"]["traces"]["generation_trace"]["total_tokens"] = 0
    payload["response"]["traces"]["generation_trace"]["estimated_cost_usd"] = 0.0

    observation = normalize_live_quality_observation(case(), payload)

    assert observation.total_tokens == 138
    assert observation.estimated_cost_usd == 0.0042


@pytest.mark.parametrize(
    "mutate_payload",
    [
        lambda payload: payload["response"]["summary"].update({"fallback_used": True}),
        lambda payload: payload["response"]["traces"]["route_trace"]["diagnostics"].update(
            {"used_fallback": True}
        ),
        lambda payload: payload["response"]["traces"]["route_trace"].update(
            {"fallbacks": ["planner_timeout"]}
        ),
        lambda payload: payload["response"]["traces"]["route_trace"]["diagnostics"].update(
            {"fallback_count": 1}
        ),
        lambda payload: payload["response"]["traces"]["generation_trace"].update(
            {"fallback_used": True}
        ),
    ],
)
def test_normalize_live_quality_observation_detects_each_fallback_signal(
    mutate_payload,
) -> None:
    payload = answer_payload()
    payload["response"]["traces"]["route_trace"]["fallbacks"] = []
    payload["response"]["traces"]["route_trace"]["diagnostics"]["retrieval_degraded"] = False
    payload["response"]["traces"]["route_trace"]["diagnostics"]["fallback_count"] = 0

    mutate_payload(payload)

    assert normalize_live_quality_observation(case(), payload).fallback_used is True


@pytest.mark.parametrize(
    "mutate_payload",
    [
        lambda payload: payload["response"]["diagnostics"]["diagnostics"].update(
            {"retrieval_degraded": True}
        ),
        lambda payload: payload["response"]["traces"]["route_trace"]["diagnostics"].update(
            {"retrieval_degraded": True}
        ),
    ],
)
def test_normalize_live_quality_observation_detects_each_degradation_signal(
    mutate_payload,
) -> None:
    payload = answer_payload()
    payload["response"]["traces"]["route_trace"]["fallbacks"] = []
    payload["response"]["traces"]["route_trace"]["diagnostics"]["retrieval_degraded"] = False

    mutate_payload(payload)

    assert normalize_live_quality_observation(case(), payload).retrieval_degraded is True


def test_run_live_case_posts_debug_answer_request_and_returns_observation() -> None:
    session = FakeSession(FakeResponse(answer_payload()))

    result = run_live_case(
        settings=settings(),
        policy=policy(),
        case=case(),
        http_session=session,
        request_id_factory=lambda: "fixed-id",
    )

    assert isinstance(result, LiveQualityCaseRunResult)
    assert result.case_id == "grounded_mapo_tofu"
    assert result.observation == normalize_live_quality_observation(case(), answer_payload())
    assert result.checks == ()
    assert session.posts == [
        {
            "url": "https://serving.example.com/api/v1/debug/answers",
            "json": {
                "question": "How do I make mapo tofu?",
                "stream": False,
                "explain_routing": True,
            },
            "headers": {
                "X-Request-ID": "live-quality-gate-fixed-id",
                "Authorization": "Bearer serving-token",
            },
            "timeout": 12.5,
        }
    ]
    assert session.closed is False


def test_run_live_case_discards_query_and_fragment_when_building_debug_answer_url() -> None:
    session = FakeSession(FakeResponse(answer_payload()))

    run_live_case(
        settings=settings(api_url="https://serving.example.com/api?debug=true#frag/"),
        policy=policy(),
        case=case(),
        http_session=session,
        request_id_factory=lambda: "fixed-id",
    )

    assert session.posts[0]["url"] == "https://serving.example.com/api/v1/debug/answers"


def test_run_live_case_omits_authorization_header_when_token_is_absent() -> None:
    session = FakeSession(FakeResponse(answer_payload()))

    run_live_case(
        settings=settings(api_token=None),
        policy=policy(),
        case=case(),
        http_session=session,
        request_id_factory=lambda: "fixed-id",
    )

    assert session.posts[0]["headers"] == {"X-Request-ID": "live-quality-gate-fixed-id"}


def test_run_live_case_omits_authorization_header_when_token_is_empty_string() -> None:
    session = FakeSession(FakeResponse(answer_payload()))

    run_live_case(
        settings=settings(api_token=""),
        policy=policy(),
        case=case(),
        http_session=session,
        request_id_factory=lambda: "fixed-id",
    )

    assert session.posts[0]["headers"] == {"X-Request-ID": "live-quality-gate-fixed-id"}


def test_run_live_case_returns_sanitized_failed_check_on_request_failure(monkeypatch) -> None:
    session = FakeSession(FakeResponse(error=requests.Timeout("serving-token leaked detail")))
    counter = iter([100.0, 100.25])
    monkeypatch.setattr("scripts.live_quality_gate.client.perf_counter", lambda: next(counter))

    result = run_live_case(
        settings=settings(),
        policy=policy(),
        case=case(),
        http_session=session,
        request_id_factory=lambda: "fixed-id",
    )

    assert result.case_id == "grounded_mapo_tofu"
    assert result.observation is None
    assert len(result.checks) == 1
    check = result.checks[0]
    assert check.code == "LIVE_QUALITY_REQUEST_FAILED"
    assert check.failure_type is GateFailureType.DEPENDENCY_UNAVAILABLE
    assert check.duration_ms == 250.0

    check_payload = check.to_dict()
    assert "serving-token" not in repr(check_payload)
    assert "leaked detail" not in repr(check_payload)


def test_run_live_case_returns_sanitized_failed_check_on_validation_failure(
    monkeypatch,
) -> None:
    session = FakeSession(
        FakeResponse(
            {
                "response": {
                    "summary": {"answer": "missing pieces"},
                    "payload": {
                        "token": "serving-token",
                        "detail": "secret-text invalid/missing payload",
                    },
                    "exception": {"message": "Validation exploded with serving-token secret-text"},
                }
            }
        )
    )
    counter = iter([10.0, 10.123])
    monkeypatch.setattr("scripts.live_quality_gate.client.perf_counter", lambda: next(counter))

    result = run_live_case(
        settings=settings(),
        policy=policy(),
        case=case(),
        http_session=session,
        request_id_factory=lambda: "fixed-id",
    )

    assert result.observation is None
    assert len(result.checks) == 1
    check = result.checks[0]
    assert check.code == "LIVE_QUALITY_REQUEST_FAILED"
    assert check.failure_type is GateFailureType.DEPENDENCY_UNAVAILABLE
    assert check.duration_ms == pytest.approx(123.0)

    check_payload = check.to_dict()
    sanitized_repr = repr(check_payload)
    check_repr = repr(check)
    for secret in (
        "serving-token",
        "secret-text",
        "invalid/missing payload",
        "Validation exploded",
    ):
        assert secret not in sanitized_repr
        assert secret not in check_repr


@pytest.mark.parametrize(
    ("missing_path", "secret"),
    [
        (("response", "summary", "latency_ms"), "latency-secret"),
        (("response", "summary", "prompt_tokens"), "prompt-secret"),
        (
            ("response", "traces", "route_trace", "diagnostics", "retrieval_degraded"),
            "degraded-secret",
        ),
        (("response", "traces", "generation_trace", "total_tokens"), "generation-secret"),
        (("response", "traces", "route_trace", "strategy"), "strategy-secret"),
    ],
)
def test_run_live_case_treats_sparse_debug_payload_as_contract_invalid(
    monkeypatch,
    missing_path: tuple[str, ...],
    secret: str,
) -> None:
    payload = delete_nested_key(answer_payload(), *missing_path)
    payload["response"]["summary"]["answer"] = f"{secret} should never leak"
    session = FakeSession(FakeResponse(payload))
    counter = iter([50.0, 50.25])
    monkeypatch.setattr("scripts.live_quality_gate.client.perf_counter", lambda: next(counter))

    result = run_live_case(
        settings=settings(),
        policy=policy(),
        case=case(),
        http_session=session,
        request_id_factory=lambda: "fixed-id",
    )

    assert_sanitized_request_failed_result(
        result,
        expected_duration_ms=250.0,
        secrets=(secret, "should never leak"),
    )


@pytest.mark.parametrize(
    ("missing_path", "secret"),
    [
        (
            ("response", "grounding", "evidence_documents", 0, "recipe_name"),
            "recipe-name-secret",
        ),
        (("response", "grounding", "evidence_documents", 0, "source"), "source-secret"),
        (("response", "grounding", "evidence_documents", 0, "content"), "content-secret"),
        (("response", "grounding", "evidence_documents", 0, "score"), "score-secret"),
        (
            ("response", "traces", "route_trace", "stages", "hybrid", "sources"),
            "stage-sources-secret",
        ),
    ],
)
def test_run_live_case_treats_sparse_nested_contract_fields_as_invalid(
    monkeypatch,
    missing_path: tuple[str | int, ...],
    secret: str,
) -> None:
    payload = deepcopy(answer_payload())
    cursor: Any = payload
    for key in missing_path[:-1]:
        cursor = cursor[key]
    del cursor[missing_path[-1]]
    payload["response"]["summary"]["answer"] = f"{secret} should never leak"
    session = FakeSession(FakeResponse(payload))
    counter = iter([80.0, 80.25])
    monkeypatch.setattr("scripts.live_quality_gate.client.perf_counter", lambda: next(counter))

    result = run_live_case(
        settings=settings(),
        policy=policy(),
        case=case(),
        http_session=session,
        request_id_factory=lambda: "fixed-id",
    )

    assert_sanitized_request_failed_result(
        result,
        expected_duration_ms=250.0,
        secrets=(secret, "should never leak"),
    )


def test_run_live_case_treats_empty_route_stages_as_contract_invalid(monkeypatch) -> None:
    payload = answer_payload()
    payload["response"]["traces"]["route_trace"]["stages"] = {}
    payload["response"]["summary"]["answer"] = "stage-empty-secret should never leak"
    session = FakeSession(FakeResponse(payload))
    counter = iter([90.0, 90.25])
    monkeypatch.setattr("scripts.live_quality_gate.client.perf_counter", lambda: next(counter))

    result = run_live_case(
        settings=settings(),
        policy=policy(),
        case=case(),
        http_session=session,
        request_id_factory=lambda: "fixed-id",
    )

    assert_sanitized_request_failed_result(
        result,
        expected_duration_ms=250.0,
        secrets=("stage-empty-secret", "should never leak"),
    )


@pytest.mark.parametrize("json_payload", [["serving-token", "secret-text"], "serving-token"])
def test_run_live_case_returns_sanitized_failed_check_on_non_dict_json_response(
    monkeypatch,
    json_payload: Any,
) -> None:
    session = FakeSession(FakeResponse(json_payload))
    counter = iter([70.0, 70.333])
    monkeypatch.setattr("scripts.live_quality_gate.client.perf_counter", lambda: next(counter))

    result = run_live_case(
        settings=settings(),
        policy=policy(),
        case=case(),
        http_session=session,
        request_id_factory=lambda: "fixed-id",
    )

    assert result.observation is None
    assert len(result.checks) == 1
    check = result.checks[0]
    assert check.code == "LIVE_QUALITY_REQUEST_FAILED"
    assert check.failure_type is GateFailureType.DEPENDENCY_UNAVAILABLE
    assert check.duration_ms == pytest.approx(333.0)

    sanitized_repr = repr(check.to_dict())
    check_repr = repr(check)
    for secret in ("serving-token", "secret-text"):
        assert secret not in sanitized_repr
        assert secret not in check_repr


def test_run_live_case_closes_only_owned_session(monkeypatch) -> None:
    supplied_session = FakeSession(FakeResponse(answer_payload()))

    run_live_case(
        settings=settings(),
        policy=policy(),
        case=case(),
        http_session=supplied_session,
        request_id_factory=lambda: "supplied-session",
    )

    owned_session = FakeSession(FakeResponse(answer_payload()))
    monkeypatch.setattr("scripts.live_quality_gate.client.requests.Session", lambda: owned_session)

    run_live_case(
        settings=settings(),
        policy=policy(),
        case=case(),
        request_id_factory=lambda: "owned-session",
    )

    assert supplied_session.closed is False
    assert owned_session.closed is True

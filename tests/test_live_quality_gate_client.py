from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

import pytest
import requests

from scripts.gates import GateFailureType
from scripts.live_quality_gate import client as client_module
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
        lines: list[str],
        *,
        content_type: str = "text/event-stream; charset=utf-8",
        error: Exception | None = None,
    ) -> None:
        self.lines = lines
        self.headers = {"content-type": content_type}
        self.error = error
        self.closed = False

    def raise_for_status(self) -> None:
        if self.error is not None:
            raise self.error

    def iter_lines(self, *, decode_unicode: bool) -> list[str]:
        assert decode_unicode is True
        return self.lines

    def close(self) -> None:
        self.closed = True


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
        stream: bool,
    ) -> FakeResponse:
        assert stream is True
        self.posts.append(
            {
                "url": url,
                "json": json,
                "headers": headers,
                "timeout": timeout,
                "stream": stream,
            }
        )
        return self.response

    def close(self) -> None:
        self.closed = True


def sse_lines(*events: tuple[str, dict[str, Any]]) -> list[str]:
    lines: list[str] = []
    for name, data in events:
        lines.extend(
            [
                f"event: {name}",
                f"data: {json.dumps(data, ensure_ascii=False)}",
                "",
            ]
        )
    return lines


def success_response(payload: dict[str, Any] | None = None) -> FakeResponse:
    result_payload = answer_payload() if payload is None else payload
    answer = result_payload["response"]["summary"]["answer"]
    return FakeResponse(
        sse_lines(
            ("message", {"message": "Running query routing..."}),
            ("chunk", {"content": answer}),
            ("result", result_payload),
            ("done", {"ok": True}),
        )
    )


def result_response(payload: dict[str, Any]) -> FakeResponse:
    answer = payload.get("response", {}).get("summary", {}).get("answer", "invalid")
    return FakeResponse(
        sse_lines(
            ("chunk", {"content": answer}),
            ("result", payload),
            ("done", {"ok": True}),
        )
    )


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
        schema_version=2,
        top_k=6,
        timeouts=LiveQualityTimeouts(request_seconds=12.5, judge_seconds=45.0),
        judge=LiveQualityJudgePolicy(
            required=True,
            score_names=["faithfulness", "answer_relevance"],
            minimum_score=0.8,
        ),
        thresholds=LiveQualityThresholds(
            minimum_case_count=1,
            minimum_rerank_observation_count=1,
            minimum_pass_rate=0.9,
            minimum_deterministic_pass_rate=0.9,
            minimum_judge_pass_rate=0.9,
            minimum_recall_at_k=0.7,
            minimum_mrr=0.6,
            minimum_ndcg_at_k=0.7,
            maximum_fallback_rate=0.0,
            maximum_retrieval_degradation_rate=0.0,
            maximum_p95_ttft_ms=5000.0,
            maximum_p95_retrieval_latency_ms=3000.0,
            maximum_p95_rerank_latency_ms=2000.0,
            maximum_p95_generation_latency_ms=20000.0,
            maximum_p95_latency_ms=25000.0,
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
                    "total_latency_ms": 850.0,
                    "stages": {
                        "hybrid": {"latency_ms": 500.0, "sources": {"vector": 2}},
                        "post_process": {
                            "latency_ms": 300.0,
                            "sources": {"rerank": 1},
                            "rerank_attempted": True,
                            "rerank_succeeded": True,
                            "rerank_latency_ms": 250.0,
                        },
                        "empty": {"latency_ms": 50.0, "sources": {"zero_count": 0}},
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
                    "total_latency_ms": 4000.0,
                    "first_token_latency_ms": 1200.0,
                    "prompt_tokens": 202,
                    "completion_tokens": 74,
                    "total_tokens": 276,
                    "estimated_cost_usd": 0.0084,
                },
            },
        }
    }


def normalize(payload: dict[str, Any]) -> LiveQualityObservation:
    return normalize_live_quality_observation(
        case(),
        payload,
        ttft_ms=1250.0,
        latency_ms=6000.0,
    )


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
    observation = normalize(answer_payload())

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
        ttft_ms=1250.0,
        latency_ms=6000.0,
        retrieval_latency_ms=850.0,
        rerank_attempted=True,
        rerank_succeeded=True,
        rerank_latency_ms=250.0,
        generation_latency_ms=4000.0,
        generation_first_token_latency_ms=1200.0,
        prompt_tokens=101,
        completion_tokens=37,
        total_tokens=276,
        estimated_cost_usd=0.0084,
    )


def test_normalize_live_quality_observation_preserves_duplicate_ranked_recipes() -> None:
    observation = normalize(answer_payload())

    assert observation.ranked_recipe_names == ("Mapo Tofu", "Dan Dan Noodles", "Mapo Tofu")


def test_normalize_live_quality_observation_ignores_zero_count_stage_sources() -> None:
    payload = answer_payload()
    payload["response"]["traces"]["route_trace"]["stages"] = {
        "post_process": {
            "latency_ms": 1.0,
            "sources": {},
            "rerank_attempted": False,
            "rerank_succeeded": False,
            "rerank_latency_ms": None,
        },
        "empty": {"sources": {"zero_count": 0, "negative_count": -1}},
        "filled": {"sources": {"vector": 2}},
    }

    observation = normalize(payload)

    assert observation.sources == frozenset({"vector", "graph"})


def test_normalize_live_quality_observation_ignores_empty_stage_source_keys() -> None:
    payload = answer_payload()
    payload["response"]["traces"]["route_trace"]["stages"] = {
        "post_process": {
            "latency_ms": 1.0,
            "sources": {},
            "rerank_attempted": False,
            "rerank_succeeded": False,
            "rerank_latency_ms": None,
        },
        "filled": {"sources": {"": 1, "vector": 2}},
    }

    observation = normalize(payload)

    assert observation.sources == frozenset({"vector", "graph"})
    assert "" not in observation.sources


def test_normalize_live_quality_observation_falls_back_to_route_strategy() -> None:
    payload = answer_payload()
    payload["response"]["summary"]["strategy"] = ""
    payload["response"]["traces"]["route_trace"]["strategy"] = "graph_rag"

    observation = normalize(payload)

    assert observation.strategy == "graph_rag"


def test_normalize_live_quality_observation_prefers_generation_total_tokens_and_cost() -> None:
    observation = normalize(answer_payload())

    assert observation.prompt_tokens == 101
    assert observation.completion_tokens == 37
    assert observation.total_tokens == 276
    assert observation.estimated_cost_usd == 0.0084


def test_normalize_live_quality_observation_falls_back_to_summary_total_tokens_and_cost() -> None:
    payload = answer_payload()
    payload["response"]["traces"]["generation_trace"]["total_tokens"] = 0
    payload["response"]["traces"]["generation_trace"]["estimated_cost_usd"] = 0.0

    observation = normalize(payload)

    assert observation.total_tokens == 138
    assert observation.estimated_cost_usd == 0.0042


@pytest.mark.parametrize(
    ("mutate_payload", "message"),
    [
        (
            lambda payload: payload["response"]["traces"]["route_trace"].update(
                {"total_latency_ms": 0.0}
            ),
            "retrieval latency is missing",
        ),
        (
            lambda payload: payload["response"]["traces"]["generation_trace"].update(
                {"total_latency_ms": 0.0}
            ),
            "generation latency is missing",
        ),
        (
            lambda payload: payload["response"]["traces"]["generation_trace"].update(
                {"first_token_latency_ms": 0.0}
            ),
            "generation first-token latency is missing",
        ),
        (
            lambda payload: payload["response"]["traces"]["route_trace"]["stages"][
                "post_process"
            ].update({"rerank_latency_ms": None}),
            "rerank latency is missing",
        ),
        (
            lambda payload: payload["response"]["traces"]["route_trace"]["stages"][
                "post_process"
            ].update({"rerank_attempted": False}),
            "rerank timing is inconsistent",
        ),
    ],
)
def test_normalize_live_quality_observation_rejects_invalid_trace_timings(
    mutate_payload,
    message: str,
) -> None:
    payload = answer_payload()
    mutate_payload(payload)

    with pytest.raises(ValueError, match=message):
        normalize(payload)


def test_normalize_live_quality_observation_requires_post_process_stage() -> None:
    payload = answer_payload()
    del payload["response"]["traces"]["route_trace"]["stages"]["post_process"]

    with pytest.raises(ValueError, match="post-process"):
        normalize(payload)


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

    assert normalize(payload).fallback_used is True


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

    assert normalize(payload).retrieval_degraded is True


def test_run_live_case_posts_debug_answer_request_and_returns_observation() -> None:
    clock_values = iter([100.0, 101.25, 106.0])
    response = success_response()
    session = FakeSession(response)

    result = run_live_case(
        settings=settings(),
        policy=policy(),
        case=case(),
        http_session=session,
        request_id_factory=lambda: "fixed-id",
        clock=lambda: next(clock_values),
    )

    assert isinstance(result, LiveQualityCaseRunResult)
    assert result.case_id == "grounded_mapo_tofu"
    assert result.checks == ()
    assert result.observation == normalize(answer_payload())
    assert result.observation.ttft_ms == 1250.0
    assert result.observation.latency_ms == 6000.0
    assert result.observation.retrieval_latency_ms == 850.0
    assert result.observation.rerank_attempted is True
    assert result.observation.rerank_succeeded is True
    assert result.observation.rerank_latency_ms == 250.0
    assert result.observation.generation_latency_ms == 4000.0
    assert result.observation.generation_first_token_latency_ms == 1200.0
    assert session.posts == [
        {
            "url": "https://serving.example.com/api/v1/debug/answers/stream",
            "json": {
                "question": "How do I make mapo tofu?",
                "explain_routing": True,
            },
            "headers": {
                "X-Request-ID": "live-quality-gate-fixed-id",
                "Authorization": "Bearer serving-token",
            },
            "timeout": 12.5,
            "stream": True,
        }
    ]
    assert response.closed is True
    assert session.closed is False


def test_run_live_case_discards_query_and_fragment_when_building_debug_answer_url() -> None:
    session = FakeSession(success_response())
    clock_values = iter([100.0, 101.0, 102.0])

    run_live_case(
        settings=settings(api_url="https://serving.example.com/api?debug=true#frag/"),
        policy=policy(),
        case=case(),
        http_session=session,
        request_id_factory=lambda: "fixed-id",
        clock=lambda: next(clock_values),
    )

    assert session.posts[0]["url"] == "https://serving.example.com/api/v1/debug/answers/stream"


def test_run_live_case_omits_authorization_header_when_token_is_absent() -> None:
    session = FakeSession(success_response())
    clock_values = iter([100.0, 101.0, 102.0])

    run_live_case(
        settings=settings(api_token=None),
        policy=policy(),
        case=case(),
        http_session=session,
        request_id_factory=lambda: "fixed-id",
        clock=lambda: next(clock_values),
    )

    assert session.posts[0]["headers"] == {"X-Request-ID": "live-quality-gate-fixed-id"}


def test_run_live_case_omits_authorization_header_when_token_is_empty_string() -> None:
    session = FakeSession(success_response())
    clock_values = iter([100.0, 101.0, 102.0])

    run_live_case(
        settings=settings(api_token=""),
        policy=policy(),
        case=case(),
        http_session=session,
        request_id_factory=lambda: "fixed-id",
        clock=lambda: next(clock_values),
    )

    assert session.posts[0]["headers"] == {"X-Request-ID": "live-quality-gate-fixed-id"}


@pytest.mark.parametrize(
    ("case_name", "events", "expected_duration_ms"),
    [
        (
            "no_non_empty_chunk",
            [
                ("chunk", {"content": ""}),
                ("result", answer_payload()),
                ("done", {"ok": True}),
            ],
            2000.0,
        ),
        (
            "duplicate_result",
            [
                ("chunk", {"content": "x"}),
                ("result", answer_payload()),
                ("result", answer_payload()),
                ("done", {"ok": True}),
            ],
            3000.0,
        ),
        (
            "missing_result",
            [("chunk", {"content": "x"}), ("done", {"ok": True})],
            2000.0,
        ),
        (
            "missing_done",
            [("chunk", {"content": "x"}), ("result", answer_payload())],
            3000.0,
        ),
        (
            "error_event",
            [
                (
                    "error",
                    {
                        "error": {
                            "code": "ANSWER_FAILED",
                            "message": "safe server-secret",
                        }
                    },
                ),
                ("done", {"ok": True}),
            ],
            1000.0,
        ),
        (
            "event_after_done",
            [("done", {"ok": True}), ("chunk", {"content": "x"})],
            1000.0,
        ),
    ],
)
def test_run_live_case_rejects_invalid_sse_protocol(
    case_name: str,
    events: list[tuple[str, dict[str, Any]]],
    expected_duration_ms: float,
) -> None:
    del case_name
    response = FakeResponse(sse_lines(*events))
    session = FakeSession(response)
    counter = iter(float(value) for value in range(100, 110))

    result = run_live_case(
        settings=settings(),
        policy=policy(),
        case=case(),
        http_session=session,
        request_id_factory=lambda: "fixed-id",
        clock=lambda: next(counter),
    )

    assert_sanitized_request_failed_result(
        result,
        expected_duration_ms=expected_duration_ms,
        secrets=("serving-token", "safe server-secret", "ANSWER_FAILED"),
    )
    assert response.closed is True


@pytest.mark.parametrize(
    ("event_name", "event_data"),
    [
        ("chunk", {"content": ""}),
        ("message", {"message": "late progress"}),
    ],
)
def test_run_live_case_rejects_chunk_or_message_after_result(
    event_name: str,
    event_data: dict[str, Any],
) -> None:
    payload = answer_payload()
    response = FakeResponse(
        sse_lines(
            ("chunk", {"content": payload["response"]["summary"]["answer"]}),
            ("result", payload),
            (event_name, event_data),
            ("done", {"ok": True}),
        )
    )
    counter = iter([100.0, 101.0, 102.0, 103.0])

    result = run_live_case(
        settings=settings(),
        policy=policy(),
        case=case(),
        http_session=FakeSession(response),
        clock=lambda: next(counter),
    )

    assert_sanitized_request_failed_result(
        result,
        expected_duration_ms=3000.0,
        secrets=("serving-token", "late progress"),
    )
    assert response.closed is True


def test_run_live_case_rejects_ttft_after_result_arrival() -> None:
    response = success_response()
    counter = iter([100.0, 106.0, 105.0, 107.0])

    result = run_live_case(
        settings=settings(),
        policy=policy(),
        case=case(),
        http_session=FakeSession(response),
        clock=lambda: next(counter),
    )

    assert_sanitized_request_failed_result(
        result,
        expected_duration_ms=7000.0,
        secrets=("serving-token",),
    )
    assert response.closed is True


def test_run_live_case_rejects_non_sse_content_type() -> None:
    response = FakeResponse([], content_type="application/json; charset=utf-8")
    counter = iter([10.0, 10.25])

    result = run_live_case(
        settings=settings(),
        policy=policy(),
        case=case(),
        http_session=FakeSession(response),
        clock=lambda: next(counter),
    )

    assert_sanitized_request_failed_result(
        result,
        expected_duration_ms=250.0,
        secrets=("serving-token",),
    )
    assert response.closed is True


def test_run_live_case_rejects_chunk_result_answer_mismatch() -> None:
    response = FakeResponse(
        sse_lines(
            ("chunk", {"content": "different answer"}),
            ("result", answer_payload()),
            ("done", {"ok": True}),
        )
    )
    counter = iter([10.0, 10.1, 10.2, 10.3])

    result = run_live_case(
        settings=settings(),
        policy=policy(),
        case=case(),
        http_session=FakeSession(response),
        clock=lambda: next(counter),
    )

    assert_sanitized_request_failed_result(
        result,
        expected_duration_ms=300.0,
        secrets=("serving-token", "different answer"),
    )
    assert response.closed is True


def test_run_live_case_returns_structured_failure_for_invalid_client_timing() -> None:
    response = success_response()
    counter = iter([10.0, 10.0, 10.0])

    result = run_live_case(
        settings=settings(),
        policy=policy(),
        case=case(),
        http_session=FakeSession(response),
        clock=lambda: next(counter),
    )

    assert_sanitized_request_failed_result(
        result,
        expected_duration_ms=0.0,
        secrets=("serving-token",),
    )
    assert response.closed is True


@pytest.mark.parametrize(
    "clock",
    [
        pytest.param(
            lambda: (_ for _ in ()).throw(RuntimeError("raising-clock-secret")),
            id="raising",
        ),
        pytest.param(lambda: next(iter(())), id="exhausted"),
    ],
)
def test_run_live_case_returns_structured_failure_when_initial_clock_raises(clock) -> None:
    session = FakeSession(success_response())

    result = run_live_case(
        settings=settings(),
        policy=policy(),
        case=case(),
        http_session=session,
        clock=clock,
    )

    assert_sanitized_request_failed_result(
        result,
        expected_duration_ms=0.0,
        secrets=("serving-token", "raising-clock-secret"),
    )
    assert session.posts == []


def test_run_live_case_returns_structured_failure_for_non_numeric_clock_sample() -> None:
    session = FakeSession(success_response())

    result = run_live_case(
        settings=settings(),
        policy=policy(),
        case=case(),
        http_session=session,
        clock=lambda: "non-numeric-clock-secret",
    )

    assert_sanitized_request_failed_result(
        result,
        expected_duration_ms=0.0,
        secrets=("serving-token", "non-numeric-clock-secret"),
    )
    assert session.posts == []


def test_run_live_case_failure_duration_clock_cannot_mask_structured_failure() -> None:
    response = FakeResponse([], error=requests.Timeout("transport-secret"))
    counter = iter([100.0])

    result = run_live_case(
        settings=settings(),
        policy=policy(),
        case=case(),
        http_session=FakeSession(response),
        clock=lambda: next(counter),
    )

    assert_sanitized_request_failed_result(
        result,
        expected_duration_ms=0.0,
        secrets=("serving-token", "transport-secret"),
    )
    assert response.closed is True


def test_iter_sse_events_accepts_lf_crlf_comments_and_multiple_data_lines() -> None:
    events = tuple(
        client_module._iter_sse_events(
            [
                ": keep-alive",
                "event: message",
                'data: {"message": "routing"}',
                "",
                ": another comment\r",
                "event: chunk\r",
                'data: {"content":\r',
                'data: "tofu"}\r',
                "\r",
            ]
        )
    )

    assert [(event.name, event.data) for event in events] == [
        ("message", {"message": "routing"}),
        ("chunk", {"content": "tofu"}),
    ]


@pytest.mark.parametrize(
    ("lines", "message"),
    [
        (["event: chunk", 'data: {"content": "x"}'], "unterminated"),
        (["event", ""], "invalid"),
        (["event: chunk", "data: not-json", ""], "Expecting value"),
    ],
)
def test_iter_sse_events_rejects_invalid_framing(
    lines: list[str],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        tuple(client_module._iter_sse_events(lines))


def test_run_live_case_returns_sanitized_failed_check_on_request_failure() -> None:
    response = FakeResponse([], error=requests.Timeout("serving-token leaked detail"))
    session = FakeSession(response)
    counter = iter([100.0, 100.25])

    result = run_live_case(
        settings=settings(),
        policy=policy(),
        case=case(),
        http_session=session,
        request_id_factory=lambda: "fixed-id",
        clock=lambda: next(counter),
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
    assert response.closed is True


def test_run_live_case_returns_sanitized_failed_check_on_validation_failure() -> None:
    payload = {
        "response": {
            "summary": {"answer": "missing pieces"},
            "payload": {
                "token": "serving-token",
                "detail": "secret-text invalid/missing payload",
            },
            "exception": {"message": "Validation exploded with serving-token secret-text"},
        }
    }
    session = FakeSession(result_response(payload))
    counter = iter([10.0, 10.1, 10.2, 10.3])

    result = run_live_case(
        settings=settings(),
        policy=policy(),
        case=case(),
        http_session=session,
        request_id_factory=lambda: "fixed-id",
        clock=lambda: next(counter),
    )

    assert result.observation is None
    assert len(result.checks) == 1
    check = result.checks[0]
    assert check.code == "LIVE_QUALITY_REQUEST_FAILED"
    assert check.failure_type is GateFailureType.DEPENDENCY_UNAVAILABLE
    assert check.duration_ms == pytest.approx(300.0)

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
        (("response", "traces", "route_trace", "total_latency_ms"), "route-timing-secret"),
        (
            ("response", "traces", "route_trace", "diagnostics", "retrieval_degraded"),
            "degraded-secret",
        ),
        (("response", "traces", "generation_trace", "total_tokens"), "generation-secret"),
        (
            ("response", "traces", "generation_trace", "total_latency_ms"),
            "generation-timing-secret",
        ),
        (
            ("response", "traces", "generation_trace", "first_token_latency_ms"),
            "generation-ttft-secret",
        ),
        (("response", "traces", "route_trace", "strategy"), "strategy-secret"),
    ],
)
def test_run_live_case_treats_sparse_debug_payload_as_contract_invalid(
    missing_path: tuple[str, ...],
    secret: str,
) -> None:
    payload = delete_nested_key(answer_payload(), *missing_path)
    payload["response"]["summary"]["answer"] = f"{secret} should never leak"
    session = FakeSession(result_response(payload))
    counter = iter([50.0, 50.1, 50.2, 50.25])

    result = run_live_case(
        settings=settings(),
        policy=policy(),
        case=case(),
        http_session=session,
        request_id_factory=lambda: "fixed-id",
        clock=lambda: next(counter),
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
        (
            (
                "response",
                "traces",
                "route_trace",
                "stages",
                "post_process",
                "rerank_attempted",
            ),
            "rerank-attempt-secret",
        ),
        (
            (
                "response",
                "traces",
                "route_trace",
                "stages",
                "post_process",
                "rerank_succeeded",
            ),
            "rerank-success-secret",
        ),
        (
            (
                "response",
                "traces",
                "route_trace",
                "stages",
                "post_process",
                "rerank_latency_ms",
            ),
            "rerank-timing-secret",
        ),
    ],
)
def test_run_live_case_treats_sparse_nested_contract_fields_as_invalid(
    missing_path: tuple[str | int, ...],
    secret: str,
) -> None:
    payload = deepcopy(answer_payload())
    cursor: Any = payload
    for key in missing_path[:-1]:
        cursor = cursor[key]
    del cursor[missing_path[-1]]
    payload["response"]["summary"]["answer"] = f"{secret} should never leak"
    session = FakeSession(result_response(payload))
    counter = iter([80.0, 80.1, 80.2, 80.25])

    result = run_live_case(
        settings=settings(),
        policy=policy(),
        case=case(),
        http_session=session,
        request_id_factory=lambda: "fixed-id",
        clock=lambda: next(counter),
    )

    assert_sanitized_request_failed_result(
        result,
        expected_duration_ms=250.0,
        secrets=(secret, "should never leak"),
    )


def test_run_live_case_treats_empty_route_stages_as_contract_invalid() -> None:
    payload = answer_payload()
    payload["response"]["traces"]["route_trace"]["stages"] = {}
    payload["response"]["summary"]["answer"] = "stage-empty-secret should never leak"
    session = FakeSession(result_response(payload))
    counter = iter([90.0, 90.1, 90.2, 90.25])

    result = run_live_case(
        settings=settings(),
        policy=policy(),
        case=case(),
        http_session=session,
        request_id_factory=lambda: "fixed-id",
        clock=lambda: next(counter),
    )

    assert_sanitized_request_failed_result(
        result,
        expected_duration_ms=250.0,
        secrets=("stage-empty-secret", "should never leak"),
    )


def test_iter_sse_events_rejects_non_object_json_data() -> None:
    with pytest.raises(ValueError, match="must be an object"):
        tuple(client_module._iter_sse_events(["event: chunk", 'data: ["serving-token"]', ""]))


def test_run_live_case_closes_only_owned_session(monkeypatch) -> None:
    supplied_session = FakeSession(success_response())
    supplied_clock = iter([1.0, 2.0, 3.0])

    run_live_case(
        settings=settings(),
        policy=policy(),
        case=case(),
        http_session=supplied_session,
        request_id_factory=lambda: "supplied-session",
        clock=lambda: next(supplied_clock),
    )

    owned_session = FakeSession(success_response())
    monkeypatch.setattr("scripts.live_quality_gate.client.requests.Session", lambda: owned_session)
    owned_clock = iter([1.0, 2.0, 3.0])

    run_live_case(
        settings=settings(),
        policy=policy(),
        case=case(),
        request_id_factory=lambda: "owned-session",
        clock=lambda: next(owned_clock),
    )

    assert supplied_session.closed is False
    assert owned_session.closed is True

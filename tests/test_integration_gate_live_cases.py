from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from rag_modules.interfaces.api.answer_models import AnswerResponseModel
from scripts.gates import GateFailureType
from scripts.integration_gate import live_cases
from scripts.integration_gate.evaluator import evaluate_integration_metrics, evaluate_live_case
from scripts.integration_gate.live_cases import normalize_live_case_observation, run_live_case
from scripts.integration_gate.models import (
    DependencyMinimums,
    GateTimeouts,
    IntegrationGatePolicy,
    IntegrationGateSettings,
    IntegrationThresholds,
    LiveCaseObservation,
    LiveCasePolicy,
)

FORBIDDEN_FAILURE_SUBSTRINGS = ("secret", "password", "leaked", "token", "bearer")


class FakeResponse:
    def __init__(
        self,
        payload: dict[str, Any] | None = None,
        *,
        http_error: Exception | None = None,
        json_error: Exception | None = None,
        text: str = "secret response content leaked",
    ) -> None:
        self._payload = payload or {}
        self._http_error = http_error
        self._json_error = json_error
        self.text = text
        self.content = text.encode()

    def raise_for_status(self) -> None:
        if self._http_error is not None:
            raise self._http_error

    def json(self) -> dict[str, Any]:
        if self._json_error is not None:
            raise self._json_error
        return self._payload


class FakeHttpSession:
    def __init__(
        self,
        response: FakeResponse | dict[str, Any] | None = None,
        *,
        post_error: Exception | None = None,
    ) -> None:
        self._response = response or FakeResponse(answer_payload())
        self._post_error = post_error
        self.requests: list[dict[str, Any]] = []
        self.closed = False

    def post(
        self,
        url: str,
        *,
        json: dict[str, Any],
        headers: dict[str, str],
        timeout: float,
    ) -> FakeResponse:
        self.requests.append(
            {
                "url": url,
                "json": json,
                "headers": headers,
                "timeout": timeout,
            }
        )
        if self._post_error is not None:
            raise self._post_error
        if isinstance(self._response, FakeResponse):
            return self._response
        return FakeResponse(self._response)

    def close(self) -> None:
        self.closed = True


def build_settings(*, api_token: str | None = "secret-token") -> IntegrationGateSettings:
    return IntegrationGateSettings(
        api_url="http://serving.local/",
        api_token=api_token,
        neo4j_uri="bolt://neo4j.local:7687",
        neo4j_user="neo4j",
        neo4j_password="password",
        neo4j_database="neo4j",
        milvus_host="milvus.local",
        milvus_port="19530",
        milvus_collection_name="cooking_knowledge",
    )


def build_case(
    *,
    case_id: str = "combined_constrained_recommendation",
    allowed_strategies: list[str] | None = None,
    required_sources: list[str] | None = None,
    minimum_evidence_count: int = 1,
    generation_required: bool = True,
    timeout_seconds: float = 90.0,
) -> LiveCasePolicy:
    return LiveCasePolicy(
        case_id=case_id,
        question="Recommend a light tofu dish and explain the constraints.",
        allowed_strategies=allowed_strategies or ["combined"],
        required_sources=required_sources or ["vector", "graph_rag"],
        minimum_evidence_count=minimum_evidence_count,
        generation_required=generation_required,
        timeout_seconds=timeout_seconds,
    )


def build_policy(
    *,
    thresholds: IntegrationThresholds | None = None,
    cases: list[LiveCasePolicy] | None = None,
    request_timeout_seconds: float = 90.0,
) -> IntegrationGatePolicy:
    return IntegrationGatePolicy(
        schema_version=1,
        dependency_minimums=DependencyMinimums(neo4j_recipe_count=1, milvus_entity_count=1),
        timeouts=GateTimeouts(probe_seconds=10.0, request_seconds=request_timeout_seconds),
        thresholds=thresholds
        or IntegrationThresholds(
            maximum_fallback_rate=0.0,
            maximum_retrieval_degradation_rate=0.0,
            maximum_p95_latency_ms=60_000.0,
            maximum_estimated_cost_usd=1.0,
        ),
        live_cases=cases or [build_case()],
    )


def answer_payload(
    *,
    summary_strategy: str = "combined",
    route_strategy: str = "combined",
    evidence_sources: list[str] | None = None,
    stage_sources: dict[str, int] | None = None,
    summary_fallback_used: bool = False,
    route_used_fallback: bool = False,
    route_fallback_count: int = 0,
    route_fallbacks: list[str] | None = None,
    generation_fallback_used: bool = False,
    public_retrieval_degraded: bool = False,
    route_retrieval_degraded: bool = False,
    summary_latency_ms: float = 1234.0,
    summary_estimated_cost_usd: float = 0.02,
    generation_total_tokens: int = 120,
    generation_estimated_cost_usd: float = 0.03,
) -> dict[str, Any]:
    evidence_sources = evidence_sources or ["vector", "graph_rag"]
    stage_sources = stage_sources or {"vector": 1, "graph_rag": 1, "combined": 1}

    return {
        "response": {
            "summary": {
                "answer": "Use tofu with a light sauce.",
                "status": "success",
                "strategy": summary_strategy,
                "latency_ms": summary_latency_ms,
                "fallback_used": summary_fallback_used,
                "total_tokens": 999,
                "estimated_cost_usd": summary_estimated_cost_usd,
            },
            "grounding": {
                "evidence_documents": [
                    {"source": source, "content": f"evidence from {source}"}
                    for source in evidence_sources
                ]
            },
            "diagnostics": {
                "diagnostics": {
                    "retrieval_degraded": public_retrieval_degraded,
                }
            },
            "traces": {
                "route_trace": {
                    "strategy": route_strategy,
                    "stages": {
                        "retrieval": {
                            "sources": stage_sources,
                        },
                        "post_process": {
                            "sources": {"zero_ignored": 0},
                        },
                    },
                    "fallbacks": route_fallbacks or [],
                    "diagnostics": {
                        "used_fallback": route_used_fallback,
                        "fallback_count": route_fallback_count,
                        "retrieval_degraded": route_retrieval_degraded,
                    },
                },
                "generation_trace": {
                    "total_tokens": generation_total_tokens,
                    "estimated_cost_usd": generation_estimated_cost_usd,
                    "fallback_used": generation_fallback_used,
                },
            },
        }
    }


def build_observation(
    *,
    case_id: str = "combined_constrained_recommendation",
    strategy: str = "combined",
    sources: frozenset[str] = frozenset({"vector", "graph_rag", "combined"}),
    evidence_count: int = 2,
    fallback_used: bool = False,
    retrieval_degraded: bool = False,
    latency_ms: float = 1000.0,
    total_tokens: int = 120,
    estimated_cost_usd: float = 0.03,
) -> LiveCaseObservation:
    return LiveCaseObservation(
        case_id=case_id,
        strategy=strategy,
        sources=sources,
        evidence_count=evidence_count,
        fallback_used=fallback_used,
        retrieval_degraded=retrieval_degraded,
        latency_ms=latency_ms,
        total_tokens=total_tokens,
        estimated_cost_usd=estimated_cost_usd,
    )


def assert_no_forbidden_failure_details(value: object) -> None:
    text = str(value).lower()
    assert not any(forbidden in text for forbidden in FORBIDDEN_FAILURE_SUBSTRINGS)


def checks_by_name(checks: tuple[Any, ...]) -> dict[str, Any]:
    return {check.name: check for check in checks}


def failed_codes(checks: tuple[Any, ...]) -> set[str]:
    return {check.code for check in checks if not check.passed}


def test_normalize_live_case_observation_collects_strategy_sources_and_model_usage() -> None:
    case = build_case()
    response_model = AnswerResponseModel.model_validate(
        answer_payload(
            summary_strategy="combined",
            route_strategy="combined",
            stage_sources={"vector": 1, "graph_rag": 1, "combined": 1},
            evidence_sources=["vector", "graph_rag"],
            summary_latency_ms=1234.0,
            summary_estimated_cost_usd=0.02,
            generation_total_tokens=120,
            generation_estimated_cost_usd=0.03,
            generation_fallback_used=False,
        )
    )

    observation = normalize_live_case_observation(case, response_model)

    assert observation.case_id == "combined_constrained_recommendation"
    assert observation.strategy == "combined"
    assert observation.sources == frozenset({"vector", "graph_rag", "combined"})
    assert observation.evidence_count == 2
    assert observation.total_tokens == 120
    assert observation.estimated_cost_usd == 0.03
    assert observation.fallback_used is False
    assert observation.retrieval_degraded is False


def test_run_live_case_posts_debug_answer_request_with_safe_headers_and_timeout() -> None:
    case = build_case(timeout_seconds=60.0)
    policy = build_policy(request_timeout_seconds=90.0, cases=[case])
    http = FakeHttpSession(answer_payload())

    result = run_live_case(
        settings=build_settings(api_token="secret-token"),
        policy=policy,
        case=case,
        http_session=http,
        request_id_factory=lambda: "fixed-request-id",
    )

    assert result.observation is not None
    assert result.checks
    assert http.closed is False
    assert http.requests == [
        {
            "url": "http://serving.local/v1/debug/answers",
            "json": {
                "question": case.question,
                "stream": False,
                "explain_routing": True,
            },
            "headers": {
                "X-Request-ID": "integration-gate-fixed-request-id",
                "Authorization": "Bearer secret-token",
            },
            "timeout": 60.0,
        }
    ]


def test_run_live_case_omits_authorization_header_when_token_is_not_configured() -> None:
    case = build_case(timeout_seconds=90.0)
    policy = build_policy(request_timeout_seconds=45.0, cases=[case])
    http = FakeHttpSession(answer_payload())

    run_live_case(
        settings=build_settings(api_token=None),
        policy=policy,
        case=case,
        http_session=http,
        request_id_factory=lambda: "fixed-request-id",
    )

    assert http.requests[0]["headers"] == {"X-Request-ID": "integration-gate-fixed-request-id"}
    assert http.requests[0]["timeout"] == 45.0


def test_run_live_case_closes_owned_http_session(monkeypatch: pytest.MonkeyPatch) -> None:
    created_sessions: list[FakeHttpSession] = []

    class OwnedHttpSession(FakeHttpSession):
        def __init__(self) -> None:
            super().__init__(answer_payload())
            created_sessions.append(self)

    monkeypatch.setattr(live_cases.requests, "Session", OwnedHttpSession)

    result = run_live_case(
        settings=build_settings(),
        policy=build_policy(),
        case=build_case(),
        http_session=None,
        request_id_factory=lambda: "fixed-request-id",
    )

    assert result.observation is not None
    assert len(created_sessions) == 1
    assert created_sessions[0].closed is True


def test_invalid_debug_answer_contract_returns_contract_failure_without_payload() -> None:
    case = build_case()
    http = FakeHttpSession({"response": {"summary": {"answer": "secret leaked"}}})

    result = run_live_case(
        settings=build_settings(),
        policy=build_policy(cases=[case]),
        case=case,
        http_session=http,
        request_id_factory=lambda: "fixed-request-id",
    )

    assert result.case_id == case.case_id
    assert result.observation is None
    assert len(result.checks) == 1
    failure = result.checks[0]
    assert failure.code == "API_RESPONSE_CONTRACT_INVALID"
    assert failure.failure_type is GateFailureType.CONTRACT_REGRESSION
    assert failure.actual is False
    assert_no_forbidden_failure_details(failure.to_dict())


@pytest.mark.parametrize(
    ("payload_factory", "expected_code"),
    [
        (
            lambda: {"post_error": RuntimeError("Bearer secret-token leaked")},
            "SERVING_API_REQUEST_FAILED",
        ),
        (
            lambda: {
                "response": FakeResponse(
                    answer_payload(),
                    http_error=RuntimeError("HTTP 500 secret response body leaked"),
                )
            },
            "SERVING_API_REQUEST_FAILED",
        ),
        (
            lambda: {
                "response": FakeResponse(
                    answer_payload(),
                    json_error=ValueError("JSON parse leaked response body"),
                )
            },
            "SERVING_API_REQUEST_FAILED",
        ),
    ],
)
def test_transport_http_and_json_failures_are_dependency_failures_without_details(
    payload_factory: Callable[[], dict[str, object]],
    expected_code: str,
) -> None:
    case = build_case()
    http = FakeHttpSession(**payload_factory())

    result = run_live_case(
        settings=build_settings(),
        policy=build_policy(cases=[case]),
        case=case,
        http_session=http,
        request_id_factory=lambda: "fixed-request-id",
    )

    assert result.case_id == case.case_id
    assert result.observation is None
    assert len(result.checks) == 1
    failure = result.checks[0]
    assert failure.code == expected_code
    assert failure.failure_type is GateFailureType.DEPENDENCY_UNAVAILABLE
    assert failure.actual is False
    assert_no_forbidden_failure_details(failure.to_dict())


def test_missing_required_source_is_quality_regression() -> None:
    case = build_case(required_sources=["vector", "graph_rag"])
    observation = build_observation(sources=frozenset({"vector"}))

    checks = evaluate_live_case(case, observation)

    source_check = checks_by_name(checks)["case.combined_constrained_recommendation.sources"]
    assert source_check.code == "REQUIRED_SOURCE_MISSING"
    assert source_check.failure_type is GateFailureType.QUALITY_REGRESSION
    assert "REQUIRED_SOURCE_MISSING" in failed_codes(checks)


def test_missing_required_source_failure_redacts_unexpected_source_values() -> None:
    case = build_case(required_sources=["vector", "graph_rag"])
    observation = build_observation(
        sources=frozenset({"vector", "Bearer secret-token leaked source"})
    )

    checks = evaluate_live_case(case, observation)

    source_check = checks_by_name(checks)["case.combined_constrained_recommendation.sources"]
    assert source_check.code == "REQUIRED_SOURCE_MISSING"
    assert source_check.actual == {
        "present_required": ["vector"],
        "missing": ["graph_rag"],
        "unexpected_count": 1,
    }
    assert_no_forbidden_failure_details(source_check.to_dict())


def test_unexpected_strategy_is_contract_regression() -> None:
    case = build_case(allowed_strategies=["combined"])
    observation = build_observation(strategy="graph_rag")

    checks = evaluate_live_case(case, observation)

    strategy_check = checks_by_name(checks)["case.combined_constrained_recommendation.strategy"]
    assert strategy_check.code == "STRATEGY_MISMATCH"
    assert strategy_check.failure_type is GateFailureType.CONTRACT_REGRESSION


def test_unexpected_strategy_failure_redacts_unknown_strategy_values() -> None:
    case = build_case(allowed_strategies=["combined"])
    observation = build_observation(strategy="Bearer secret-token leaked strategy")

    checks = evaluate_live_case(case, observation)

    strategy_check = checks_by_name(checks)["case.combined_constrained_recommendation.strategy"]
    assert strategy_check.code == "STRATEGY_MISMATCH"
    assert strategy_check.actual == "unexpected"
    assert_no_forbidden_failure_details(strategy_check.to_dict())


def test_zero_generation_tokens_when_generation_is_required_is_contract_regression() -> None:
    case = build_case(generation_required=True)
    observation = build_observation(total_tokens=0)

    checks = evaluate_live_case(case, observation)

    model_usage_check = checks_by_name(checks)[
        "case.combined_constrained_recommendation.model_usage"
    ]
    assert model_usage_check.code == "MODEL_USAGE_NOT_PROVEN"
    assert model_usage_check.failure_type is GateFailureType.CONTRACT_REGRESSION


def test_missing_debug_trace_contract_returns_single_contract_failure_without_payload() -> None:
    case = build_case()
    payload = answer_payload()
    payload["response"]["summary"]["answer"] = "Bearer secret-token leaked answer"
    payload["response"]["traces"] = {}
    http = FakeHttpSession(payload)

    result = run_live_case(
        settings=build_settings(),
        policy=build_policy(cases=[case]),
        case=case,
        http_session=http,
        request_id_factory=lambda: "fixed-request-id",
    )

    assert result.observation is None
    assert len(result.checks) == 1
    failure = result.checks[0]
    assert failure.code == "API_RESPONSE_CONTRACT_INVALID"
    assert failure.failure_type is GateFailureType.CONTRACT_REGRESSION
    assert_no_forbidden_failure_details(failure.to_dict())


@pytest.mark.parametrize(
    "payload",
    [
        answer_payload(summary_fallback_used=True),
        answer_payload(route_used_fallback=True),
        answer_payload(route_fallback_count=1),
        answer_payload(route_fallbacks=["planner-fallback"]),
        answer_payload(generation_fallback_used=True),
    ],
)
def test_any_summary_route_or_generation_fallback_is_quality_regression(
    payload: dict[str, Any],
) -> None:
    case = build_case()
    response_model = AnswerResponseModel.model_validate(payload)

    observation = normalize_live_case_observation(case, response_model)
    checks = evaluate_live_case(case, observation)

    fallback_check = checks_by_name(checks)["case.combined_constrained_recommendation.fallback"]
    assert observation.fallback_used is True
    assert fallback_check.code == "FALLBACK_USED"
    assert fallback_check.failure_type is GateFailureType.QUALITY_REGRESSION


@pytest.mark.parametrize(
    "payload",
    [
        answer_payload(public_retrieval_degraded=True),
        answer_payload(route_retrieval_degraded=True),
    ],
)
def test_retrieval_degradation_is_quality_regression(payload: dict[str, Any]) -> None:
    case = build_case()
    response_model = AnswerResponseModel.model_validate(payload)

    observation = normalize_live_case_observation(case, response_model)
    checks = evaluate_live_case(case, observation)

    degradation_check = checks_by_name(checks)[
        "case.combined_constrained_recommendation.retrieval_degradation"
    ]
    assert observation.retrieval_degraded is True
    assert degradation_check.code == "RETRIEVAL_DEGRADED"
    assert degradation_check.failure_type is GateFailureType.QUALITY_REGRESSION


def test_insufficient_evidence_is_quality_regression() -> None:
    case = build_case(minimum_evidence_count=2)
    observation = build_observation(evidence_count=1)

    checks = evaluate_live_case(case, observation)

    evidence_check = checks_by_name(checks)[
        "case.combined_constrained_recommendation.evidence_count"
    ]
    assert evidence_check.code == "INSUFFICIENT_EVIDENCE"
    assert evidence_check.failure_type is GateFailureType.QUALITY_REGRESSION


def test_case_latency_over_timeout_is_budget_regression() -> None:
    case = build_case(timeout_seconds=90.0)
    observation = build_observation(latency_ms=90_001.0)

    checks = evaluate_live_case(case, observation)

    latency_check = checks_by_name(checks)["case.combined_constrained_recommendation.latency"]
    assert latency_check.code == "CASE_TIMEOUT_EXCEEDED"
    assert latency_check.failure_type is GateFailureType.BUDGET_REGRESSION
    assert latency_check.expected == {"maximum_ms": 90_000.0}
    assert latency_check.actual == 90_001.0


def test_aggregate_metrics_cover_global_sources_rates_p95_latency_and_cost_thresholds() -> None:
    thresholds = IntegrationThresholds(
        maximum_fallback_rate=0.2,
        maximum_retrieval_degradation_rate=0.2,
        maximum_p95_latency_ms=25.0,
        maximum_estimated_cost_usd=0.4,
    )
    policy = build_policy(thresholds=thresholds)
    observations = [
        build_observation(
            case_id="vector_case",
            sources=frozenset({"vector"}),
            latency_ms=10.0,
            estimated_cost_usd=0.10,
        ),
        build_observation(
            case_id="graph_case",
            sources=frozenset({"graph_rag"}),
            latency_ms=20.0,
            estimated_cost_usd=0.20,
            fallback_used=True,
        ),
        build_observation(
            case_id="combined_case",
            sources=frozenset({"vector", "graph_rag"}),
            latency_ms=30.0,
            estimated_cost_usd=0.15,
            retrieval_degraded=True,
        ),
    ]

    checks = evaluate_integration_metrics(policy, observations)

    by_name = checks_by_name(checks)
    assert by_name["metrics.global_vector_coverage"].passed
    assert by_name["metrics.global_graph_coverage"].passed
    assert by_name["metrics.fallback_rate"].actual == pytest.approx(1 / 3)
    assert by_name["metrics.fallback_rate"].failure_type is GateFailureType.QUALITY_REGRESSION
    assert by_name["metrics.retrieval_degradation_rate"].actual == pytest.approx(1 / 3)
    assert (
        by_name["metrics.retrieval_degradation_rate"].failure_type
        is GateFailureType.QUALITY_REGRESSION
    )
    assert by_name["metrics.p95_latency_ms"].actual == 30.0
    assert by_name["metrics.p95_latency_ms"].failure_type is GateFailureType.BUDGET_REGRESSION
    assert by_name["metrics.estimated_cost_usd"].actual == pytest.approx(0.45)
    assert by_name["metrics.estimated_cost_usd"].failure_type is GateFailureType.BUDGET_REGRESSION


def test_aggregate_metrics_fail_closed_when_no_observations_are_available() -> None:
    policy = build_policy(
        thresholds=IntegrationThresholds(
            maximum_fallback_rate=0.0,
            maximum_retrieval_degradation_rate=0.0,
            maximum_p95_latency_ms=25.0,
            maximum_estimated_cost_usd=0.4,
        )
    )

    checks = evaluate_integration_metrics(policy, [])

    by_name = checks_by_name(checks)
    assert by_name["metrics.global_vector_coverage"].code == "GLOBAL_VECTOR_COVERAGE_MISSING"
    assert by_name["metrics.global_graph_coverage"].code == "GLOBAL_GRAPH_COVERAGE_MISSING"
    assert by_name["metrics.fallback_rate"].actual == 1.0
    assert by_name["metrics.fallback_rate"].code == "METRIC_ABOVE_MAXIMUM"
    assert by_name["metrics.retrieval_degradation_rate"].actual == 1.0
    assert by_name["metrics.retrieval_degradation_rate"].code == "METRIC_ABOVE_MAXIMUM"
    assert by_name["metrics.p95_latency_ms"].code == "INSUFFICIENT_LIVE_OBSERVATIONS"
    assert by_name["metrics.p95_latency_ms"].failure_type is GateFailureType.GATE_ERROR
    assert by_name["metrics.estimated_cost_usd"].code == "INSUFFICIENT_LIVE_OBSERVATIONS"
    assert by_name["metrics.estimated_cost_usd"].failure_type is GateFailureType.GATE_ERROR

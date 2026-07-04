"""Evaluation checks for live debug-answer integration gate cases."""

from __future__ import annotations

import math
from collections.abc import Sequence

from scripts.gates import GateCheckResult, GateFailureType, numeric_threshold_check

from .models import IntegrationGatePolicy, LiveCaseObservation, LiveCasePolicy

_SAFE_STRATEGY_LABELS = frozenset(
    {
        "traditional",
        "hybrid_traditional",
        "graph_rag",
        "combined",
    }
)


def evaluate_live_case(
    case: LiveCasePolicy,
    observation: LiveCaseObservation,
) -> tuple[GateCheckResult, ...]:
    """Evaluate one normalized live debug-answer observation against its policy."""

    case_prefix = f"case.{case.case_id}"
    return (
        _strategy_check(f"{case_prefix}.strategy", case, observation),
        _sources_check(f"{case_prefix}.sources", case, observation),
        _evidence_count_check(f"{case_prefix}.evidence_count", case, observation),
        _fallback_check(f"{case_prefix}.fallback", observation),
        _retrieval_degradation_check(f"{case_prefix}.retrieval_degradation", observation),
        _model_usage_check(f"{case_prefix}.model_usage", case, observation),
        _latency_check(f"{case_prefix}.latency", case, observation),
    )


def evaluate_integration_metrics(
    policy: IntegrationGatePolicy,
    observations: Sequence[LiveCaseObservation],
) -> tuple[GateCheckResult, ...]:
    """Evaluate aggregate live-case metrics across all successful observations."""

    all_sources = frozenset(
        source for observation in observations for source in observation.sources
    )
    observation_count = len(observations)
    fallback_rate = (
        _rate(sum(observation.fallback_used for observation in observations), observation_count)
        if observation_count
        else 1.0
    )
    retrieval_degradation_rate = (
        _rate(
            sum(observation.retrieval_degraded for observation in observations),
            observation_count,
        )
        if observation_count
        else 1.0
    )
    p95_latency_ms = _nearest_rank_percentile(
        [observation.latency_ms for observation in observations],
        percentile=0.95,
    )
    total_estimated_cost_usd = sum(observation.estimated_cost_usd for observation in observations)
    p95_latency_check = (
        _insufficient_live_observations_check("metrics.p95_latency_ms")
        if observation_count == 0
        else numeric_threshold_check(
            "metrics.p95_latency_ms",
            p95_latency_ms,
            maximum=policy.thresholds.maximum_p95_latency_ms,
            failure_type=GateFailureType.BUDGET_REGRESSION,
        )
    )
    estimated_cost_check = (
        _insufficient_live_observations_check("metrics.estimated_cost_usd")
        if observation_count == 0
        else numeric_threshold_check(
            "metrics.estimated_cost_usd",
            total_estimated_cost_usd,
            maximum=policy.thresholds.maximum_estimated_cost_usd,
            failure_type=GateFailureType.BUDGET_REGRESSION,
        )
    )

    return (
        _global_source_coverage_check(
            "metrics.global_vector_coverage",
            source="vector",
            sources=all_sources,
            failure_code="GLOBAL_VECTOR_COVERAGE_MISSING",
            pass_code="GLOBAL_VECTOR_COVERAGE_OK",
        ),
        _global_source_coverage_check(
            "metrics.global_graph_coverage",
            source="graph_rag",
            sources=all_sources,
            failure_code="GLOBAL_GRAPH_COVERAGE_MISSING",
            pass_code="GLOBAL_GRAPH_COVERAGE_OK",
        ),
        numeric_threshold_check(
            "metrics.fallback_rate",
            fallback_rate,
            maximum=policy.thresholds.maximum_fallback_rate,
            failure_type=GateFailureType.QUALITY_REGRESSION,
        ),
        numeric_threshold_check(
            "metrics.retrieval_degradation_rate",
            retrieval_degradation_rate,
            maximum=policy.thresholds.maximum_retrieval_degradation_rate,
            failure_type=GateFailureType.QUALITY_REGRESSION,
        ),
        p95_latency_check,
        estimated_cost_check,
    )


def _strategy_check(
    name: str,
    case: LiveCasePolicy,
    observation: LiveCaseObservation,
) -> GateCheckResult:
    expected = tuple(case.allowed_strategies)
    actual = observation.strategy
    safe_actual = _safe_strategy_label(case, actual)
    if actual in case.allowed_strategies:
        return GateCheckResult.pass_check(
            name,
            code="STRATEGY_OK",
            expected=expected,
            actual=safe_actual,
        )
    return GateCheckResult.fail_check(
        name,
        failure_type=GateFailureType.CONTRACT_REGRESSION,
        code="STRATEGY_MISMATCH",
        expected=expected,
        actual=safe_actual,
    )


def _sources_check(
    name: str,
    case: LiveCasePolicy,
    observation: LiveCaseObservation,
) -> GateCheckResult:
    required_sources = frozenset(case.required_sources)
    missing_sources = sorted(required_sources - observation.sources)
    actual_sources = _safe_source_summary(
        required_sources=required_sources,
        observed_sources=observation.sources,
        missing_sources=missing_sources,
    )
    if not missing_sources:
        return GateCheckResult.pass_check(
            name,
            code="REQUIRED_SOURCES_OK",
            expected=sorted(required_sources),
            actual=actual_sources,
        )
    return GateCheckResult.fail_check(
        name,
        failure_type=GateFailureType.QUALITY_REGRESSION,
        code="REQUIRED_SOURCE_MISSING",
        expected={"required": sorted(required_sources), "missing": missing_sources},
        actual=actual_sources,
    )


def _evidence_count_check(
    name: str,
    case: LiveCasePolicy,
    observation: LiveCaseObservation,
) -> GateCheckResult:
    expected = {"minimum": case.minimum_evidence_count}
    actual = observation.evidence_count
    if actual >= case.minimum_evidence_count:
        return GateCheckResult.pass_check(
            name,
            code="EVIDENCE_COUNT_OK",
            expected=expected,
            actual=actual,
        )
    return GateCheckResult.fail_check(
        name,
        failure_type=GateFailureType.QUALITY_REGRESSION,
        code="INSUFFICIENT_EVIDENCE",
        expected=expected,
        actual=actual,
    )


def _fallback_check(name: str, observation: LiveCaseObservation) -> GateCheckResult:
    if not observation.fallback_used:
        return GateCheckResult.pass_check(
            name,
            code="FALLBACK_OK",
            expected=False,
            actual=False,
        )
    return GateCheckResult.fail_check(
        name,
        failure_type=GateFailureType.QUALITY_REGRESSION,
        code="FALLBACK_USED",
        expected=False,
        actual=True,
    )


def _retrieval_degradation_check(
    name: str,
    observation: LiveCaseObservation,
) -> GateCheckResult:
    if not observation.retrieval_degraded:
        return GateCheckResult.pass_check(
            name,
            code="RETRIEVAL_DEGRADATION_OK",
            expected=False,
            actual=False,
        )
    return GateCheckResult.fail_check(
        name,
        failure_type=GateFailureType.QUALITY_REGRESSION,
        code="RETRIEVAL_DEGRADED",
        expected=False,
        actual=True,
    )


def _model_usage_check(
    name: str,
    case: LiveCasePolicy,
    observation: LiveCaseObservation,
) -> GateCheckResult:
    expected = {"generation_required": case.generation_required, "minimum_tokens": 1}
    actual = observation.total_tokens
    if not case.generation_required or actual > 0:
        return GateCheckResult.pass_check(
            name,
            code="MODEL_USAGE_OK",
            expected=expected,
            actual=actual,
        )
    return GateCheckResult.fail_check(
        name,
        failure_type=GateFailureType.CONTRACT_REGRESSION,
        code="MODEL_USAGE_NOT_PROVEN",
        expected=expected,
        actual=actual,
    )


def _latency_check(
    name: str,
    case: LiveCasePolicy,
    observation: LiveCaseObservation,
) -> GateCheckResult:
    maximum_ms = case.timeout_seconds * 1000
    expected = {"maximum_ms": maximum_ms}
    actual = observation.latency_ms
    if actual <= maximum_ms:
        return GateCheckResult.pass_check(
            name,
            code="CASE_LATENCY_OK",
            expected=expected,
            actual=actual,
        )
    return GateCheckResult.fail_check(
        name,
        failure_type=GateFailureType.BUDGET_REGRESSION,
        code="CASE_TIMEOUT_EXCEEDED",
        expected=expected,
        actual=actual,
    )


def _global_source_coverage_check(
    name: str,
    *,
    source: str,
    sources: frozenset[str],
    failure_code: str,
    pass_code: str,
) -> GateCheckResult:
    if source in sources:
        return GateCheckResult.pass_check(
            name,
            code=pass_code,
            expected=True,
            actual=True,
        )
    return GateCheckResult.fail_check(
        name,
        failure_type=GateFailureType.QUALITY_REGRESSION,
        code=failure_code,
        expected=True,
        actual=False,
    )


def _safe_strategy_label(case: LiveCasePolicy, actual: str) -> str:
    safe_labels = frozenset(case.allowed_strategies) | _SAFE_STRATEGY_LABELS
    if actual in safe_labels:
        return actual
    return "unexpected"


def _safe_source_summary(
    *,
    required_sources: frozenset[str],
    observed_sources: frozenset[str],
    missing_sources: Sequence[str],
) -> dict[str, object]:
    return {
        "present_required": sorted(required_sources & observed_sources),
        "missing": list(missing_sources),
        "unexpected_count": len(observed_sources - required_sources),
    }


def _insufficient_live_observations_check(name: str) -> GateCheckResult:
    return GateCheckResult.fail_check(
        name,
        failure_type=GateFailureType.GATE_ERROR,
        code="INSUFFICIENT_LIVE_OBSERVATIONS",
        expected={"minimum_observations": 1},
        actual={"observation_count": 0},
    )


def _rate(numerator: int, denominator: int) -> float:
    return numerator / denominator


def _nearest_rank_percentile(values: Sequence[float], *, percentile: float) -> float:
    if not values:
        return 0.0
    sorted_values = sorted(values)
    index = math.ceil(percentile * len(sorted_values)) - 1
    return sorted_values[max(0, min(index, len(sorted_values) - 1))]

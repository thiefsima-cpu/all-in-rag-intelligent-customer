"""Deterministic evaluation for live quality gate cases."""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Iterable, Mapping, Sequence

from rag_modules.evaluation import percentile, retrieval_metrics
from scripts.gates import GateCheckResult, GateFailureType, numeric_threshold_check

from .models import LiveQualityCasePolicy, LiveQualityGatePolicy, LiveQualityResponseMode
from .runtime_models import DeterministicCaseResult, LiveQualityObservation

_EMPTY_RETRIEVAL_METRICS = {
    "recall_at_k": None,
    "mrr": None,
    "ndcg_at_k": None,
}


def evaluate_deterministic_case(
    case: LiveQualityCasePolicy,
    observation: LiveQualityObservation,
    *,
    top_k: int,
) -> DeterministicCaseResult:
    failures: list[str] = []

    if observation.strategy not in case.allowed_strategies:
        failures.append("strategy_mismatch")

    if not set(case.required_sources).issubset(observation.sources):
        failures.append("missing_required_sources")

    response_mode_passed = _response_mode_passed(case.expected_response_mode, observation)
    if not response_mode_passed:
        failures.append("response_mode_mismatch")

    answer = observation.answer.casefold()
    if any(required.casefold() not in answer for required in case.must_include_facts):
        failures.append("missing_required_fact")
    if any(forbidden.casefold() in answer for forbidden in case.must_not_claim):
        failures.append("forbidden_claim")
    if observation.fallback_used:
        failures.append("fallback_used")
    if observation.retrieval_degraded:
        failures.append("retrieval_degraded")

    if case.expected_response_mode is LiveQualityResponseMode.GROUNDED_ANSWER:
        retrieval = retrieval_metrics(
            observation.ranked_entity_names,
            case.relevant_items,
            k=top_k,
        )
        metrics = {
            "recall_at_k": retrieval["recall_at_k"],
            "mrr": retrieval["reciprocal_rank"],
            "ndcg_at_k": retrieval["ndcg_at_k"],
        }
        if _missing_positive_relevant_entities(
            observation.ranked_entity_names,
            case.relevant_items,
            top_k=top_k,
        ):
            failures.append("missing_relevant_entities")
    else:
        metrics = dict(_EMPTY_RETRIEVAL_METRICS)

    unique_failures = tuple(sorted(set(failures)))
    check_name = f"case.{case.case_id}.deterministic"
    if unique_failures:
        checks = (
            GateCheckResult.fail_check(
                check_name,
                failure_type=GateFailureType.QUALITY_REGRESSION,
                code="DETERMINISTIC_QUALITY_FAILED",
                actual=list(unique_failures),
            ),
        )
    else:
        checks = (
            GateCheckResult.pass_check(
                check_name,
                code="DETERMINISTIC_QUALITY_OK",
            ),
        )

    return DeterministicCaseResult(
        case_id=case.case_id,
        query_type=case.query_type,
        domain=case.domain,
        constraint_types=tuple(case.constraint_types),
        risk_tags=tuple(case.risk_tags),
        response_mode=case.expected_response_mode.value,
        strategy=observation.strategy,
        passed=not unique_failures,
        response_mode_passed=response_mode_passed,
        failures=unique_failures,
        metrics=metrics,
        checks=checks,
        observation=observation,
    )


def aggregate_live_quality_metrics(
    results: Sequence[DeterministicCaseResult],
) -> dict[str, object]:
    grouped_results = tuple(results)
    summary = _summary(grouped_results)
    summary.update(
        {
            "by_query_type": _slice_single(grouped_results, lambda result: result.query_type),
            "by_domain": _slice_single(grouped_results, lambda result: result.domain),
            "by_constraint_type": _slice_multi(
                grouped_results,
                lambda result: result.constraint_types,
            ),
            "by_risk_tag": _slice_multi(grouped_results, lambda result: result.risk_tags),
            "by_response_mode": _slice_single(grouped_results, lambda result: result.response_mode),
            "by_strategy": _slice_single(grouped_results, lambda result: result.strategy),
        }
    )
    return summary


def evaluate_policy_thresholds(
    policy: LiveQualityGatePolicy,
    metrics: Mapping[str, Any],
) -> tuple[GateCheckResult, ...]:
    checks = [
        numeric_threshold_check(
            "metrics.case_count",
            metrics.get("case_count"),
            minimum=policy.thresholds.minimum_case_count,
            failure_type=GateFailureType.COVERAGE_REGRESSION,
        ),
        numeric_threshold_check(
            "metrics.rerank_observation_count",
            metrics.get("rerank_observation_count"),
            minimum=policy.thresholds.minimum_rerank_observation_count,
            failure_type=GateFailureType.COVERAGE_REGRESSION,
        ),
        numeric_threshold_check(
            "metrics.pass_rate",
            metrics.get("pass_rate"),
            minimum=policy.thresholds.minimum_pass_rate,
            failure_type=GateFailureType.QUALITY_REGRESSION,
        ),
        numeric_threshold_check(
            "metrics.deterministic_pass_rate",
            metrics.get("deterministic_pass_rate"),
            minimum=policy.thresholds.minimum_deterministic_pass_rate,
            failure_type=GateFailureType.QUALITY_REGRESSION,
        ),
        numeric_threshold_check(
            "metrics.judge_pass_rate",
            metrics.get("judge_pass_rate"),
            minimum=policy.thresholds.minimum_judge_pass_rate,
            failure_type=GateFailureType.QUALITY_REGRESSION,
        ),
        numeric_threshold_check(
            "metrics.recall_at_k",
            metrics.get("recall_at_k"),
            minimum=policy.thresholds.minimum_recall_at_k,
            failure_type=GateFailureType.QUALITY_REGRESSION,
        ),
        numeric_threshold_check(
            "metrics.mrr",
            metrics.get("mrr"),
            minimum=policy.thresholds.minimum_mrr,
            failure_type=GateFailureType.QUALITY_REGRESSION,
        ),
        numeric_threshold_check(
            "metrics.ndcg_at_k",
            metrics.get("ndcg_at_k"),
            minimum=policy.thresholds.minimum_ndcg_at_k,
            failure_type=GateFailureType.QUALITY_REGRESSION,
        ),
        numeric_threshold_check(
            "metrics.fallback_rate",
            metrics.get("fallback_rate"),
            maximum=policy.thresholds.maximum_fallback_rate,
            failure_type=GateFailureType.QUALITY_REGRESSION,
        ),
        numeric_threshold_check(
            "metrics.retrieval_degradation_rate",
            metrics.get("retrieval_degradation_rate"),
            maximum=policy.thresholds.maximum_retrieval_degradation_rate,
            failure_type=GateFailureType.QUALITY_REGRESSION,
        ),
        numeric_threshold_check(
            "metrics.p95_ttft_ms",
            metrics.get("p95_ttft_ms"),
            maximum=policy.thresholds.maximum_p95_ttft_ms,
            failure_type=GateFailureType.BUDGET_REGRESSION,
        ),
        numeric_threshold_check(
            "metrics.p95_retrieval_latency_ms",
            metrics.get("p95_retrieval_latency_ms"),
            maximum=policy.thresholds.maximum_p95_retrieval_latency_ms,
            failure_type=GateFailureType.BUDGET_REGRESSION,
        ),
        numeric_threshold_check(
            "metrics.p95_rerank_latency_ms",
            metrics.get("p95_rerank_latency_ms"),
            maximum=policy.thresholds.maximum_p95_rerank_latency_ms,
            failure_type=GateFailureType.BUDGET_REGRESSION,
        ),
        numeric_threshold_check(
            "metrics.p95_generation_latency_ms",
            metrics.get("p95_generation_latency_ms"),
            maximum=policy.thresholds.maximum_p95_generation_latency_ms,
            failure_type=GateFailureType.BUDGET_REGRESSION,
        ),
        numeric_threshold_check(
            "metrics.p95_latency_ms",
            metrics.get("p95_latency_ms"),
            maximum=policy.thresholds.maximum_p95_latency_ms,
            failure_type=GateFailureType.BUDGET_REGRESSION,
        ),
        numeric_threshold_check(
            "metrics.estimated_cost_usd",
            metrics.get("estimated_cost_usd"),
            maximum=policy.thresholds.maximum_estimated_cost_usd,
            failure_type=GateFailureType.BUDGET_REGRESSION,
        ),
    ]
    checks.extend(_required_slice_coverage_checks(policy, metrics))
    checks.extend(_slice_threshold_checks(policy, metrics))
    return tuple(checks)


def _response_mode_passed(
    response_mode: LiveQualityResponseMode,
    observation: LiveQualityObservation,
) -> bool:
    has_evidence = bool(observation.evidence)
    if response_mode is LiveQualityResponseMode.GROUNDED_ANSWER:
        return has_evidence
    if not has_evidence:
        return True

    answer = observation.answer.casefold()
    markers = {
        LiveQualityResponseMode.NO_EVIDENCE: (
            "insufficient evidence",
            "cannot confirm",
            "证据不足",
            "无法确认",
            "无法提供",
            "无法找到",
            "没有足够证据",
            "未检索到",
            "未提供",
            "未出现",
            "并未",
            "不存在",
            "错误",
        ),
        LiveQualityResponseMode.CLARIFICATION: (
            "clarify",
            "tell me",
            "which",
            "请问",
            "请明确",
            "请您提供",
            "请补充",
            "具体指",
        ),
        LiveQualityResponseMode.CONSTRAINT_CONFLICT: (
            "conflict",
            "contradict",
            "冲突",
            "矛盾",
            "无法同时",
        ),
    }
    return any(marker in answer for marker in markers.get(response_mode, ()))


def _missing_positive_relevant_entities(
    ranked_entity_names: Sequence[str],
    relevant_entities: Mapping[str, float],
    *,
    top_k: int,
) -> bool:
    positive_labels = {
        _normalize_label(entity_name)
        for entity_name, grade in relevant_entities.items()
        if float(grade) > 0 and _normalize_label(entity_name)
    }
    required_hits = min(len(positive_labels), max(0, int(top_k)))
    if required_hits <= 0:
        return False
    retrieved = set(_top_k_labels(ranked_entity_names, top_k=top_k))
    return len(retrieved & positive_labels) < required_hits


def _top_k_labels(ranked_entity_names: Sequence[str], *, top_k: int) -> tuple[str, ...]:
    labels: list[str] = []
    for entity_name in ranked_entity_names:
        label = _normalize_label(entity_name)
        if label and label not in labels:
            labels.append(label)
        if len(labels) >= max(0, int(top_k)):
            break
    return tuple(labels)


def _normalize_label(value: object) -> str:
    return " ".join(str(value or "").strip().casefold().split())


def _deterministic_passed(result: DeterministicCaseResult) -> bool:
    return not result.failures


def _rate(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return numerator / denominator


def _judge_pass_rate(results: Sequence[DeterministicCaseResult]) -> float | None:
    applicable = [result for result in results if result.judge_passed is not None]
    if not applicable:
        return None
    return sum(1 for result in applicable if result.judge_passed) / len(applicable)


def _mean_metric(
    results: Sequence[DeterministicCaseResult],
    metric_name: str,
) -> float | None:
    values = [
        metric for result in results if (metric := result.metrics.get(metric_name)) is not None
    ]
    if not values:
        return None
    return sum(values) / len(values)


def _slice_single(
    results: Sequence[DeterministicCaseResult],
    key_func,
) -> dict[str, dict[str, object]]:
    groups: dict[str, list[DeterministicCaseResult]] = defaultdict(list)
    for result in results:
        groups[key_func(result)].append(result)
    return {key: _slice_summary(items) for key, items in groups.items()}


def _slice_multi(
    results: Sequence[DeterministicCaseResult],
    key_func,
) -> dict[str, dict[str, object]]:
    groups: dict[str, list[DeterministicCaseResult]] = defaultdict(list)
    for result in results:
        for key in key_func(result):
            groups[key].append(result)
    return {key: _slice_summary(items) for key, items in groups.items()}


def _slice_summary(results: Sequence[DeterministicCaseResult]) -> dict[str, object]:
    return _summary(tuple(results))


def _summary(results: Sequence[DeterministicCaseResult]) -> dict[str, object]:
    grouped_results = tuple(results)
    latencies = [result.observation.latency_ms for result in grouped_results]
    rerank_latencies = [
        result.observation.rerank_latency_ms
        for result in grouped_results
        if result.observation.rerank_attempted
        and result.observation.rerank_succeeded
        and result.observation.rerank_latency_ms is not None
    ]
    return {
        "case_count": len(grouped_results),
        "pass_rate": _rate(
            sum(1 for result in grouped_results if result.passed), len(grouped_results)
        ),
        "deterministic_pass_rate": _rate(
            sum(1 for result in grouped_results if _deterministic_passed(result)),
            len(grouped_results),
        ),
        "judge_pass_rate": _judge_pass_rate(grouped_results),
        "recall_at_k": _mean_metric(grouped_results, "recall_at_k"),
        "mrr": _mean_metric(grouped_results, "mrr"),
        "ndcg_at_k": _mean_metric(grouped_results, "ndcg_at_k"),
        "fallback_rate": _rate(
            sum(1 for result in grouped_results if result.observation.fallback_used),
            len(grouped_results),
        ),
        "retrieval_degradation_rate": _rate(
            sum(1 for result in grouped_results if result.observation.retrieval_degraded),
            len(grouped_results),
        ),
        "p95_ttft_ms": (
            percentile(
                [result.observation.ttft_ms for result in grouped_results],
                0.95,
            )
            if grouped_results
            else 0.0
        ),
        "p95_retrieval_latency_ms": (
            percentile(
                [result.observation.retrieval_latency_ms for result in grouped_results],
                0.95,
            )
            if grouped_results
            else 0.0
        ),
        "rerank_observation_count": len(rerank_latencies),
        "p95_rerank_latency_ms": (percentile(rerank_latencies, 0.95) if rerank_latencies else None),
        "p95_generation_latency_ms": (
            percentile(
                [result.observation.generation_latency_ms for result in grouped_results],
                0.95,
            )
            if grouped_results
            else 0.0
        ),
        "p95_generation_first_token_latency_ms": (
            percentile(
                [
                    result.observation.generation_first_token_latency_ms
                    for result in grouped_results
                ],
                0.95,
            )
            if grouped_results
            else 0.0
        ),
        "p95_latency_ms": percentile(latencies, 0.95) if latencies else 0.0,
        "estimated_cost_usd": round(
            sum(result.observation.estimated_cost_usd for result in grouped_results),
            8,
        ),
        "avg_judge_scores": _average_judge_scores(grouped_results),
    }


def _average_judge_scores(results: Iterable[DeterministicCaseResult]) -> dict[str, float]:
    totals: dict[str, float] = defaultdict(float)
    counts: dict[str, int] = defaultdict(int)
    for result in results:
        if result.judge_scores is None:
            continue
        for score_name, score_value in result.judge_scores.items():
            totals[score_name] += score_value
            counts[score_name] += 1
    return {
        score_name: totals[score_name] / counts[score_name]
        for score_name in totals
        if counts[score_name] > 0
    }


def _required_slice_coverage_checks(
    policy: LiveQualityGatePolicy,
    metrics: Mapping[str, Any],
) -> list[GateCheckResult]:
    groups = {
        "risk_tags": (policy.required_slice_coverage.risk_tags, metrics.get("by_risk_tag")),
        "query_types": (
            policy.required_slice_coverage.query_types,
            metrics.get("by_query_type"),
        ),
        "domains": (policy.required_slice_coverage.domains, metrics.get("by_domain")),
        "constraint_types": (
            policy.required_slice_coverage.constraint_types,
            metrics.get("by_constraint_type"),
        ),
        "response_modes": (
            policy.required_slice_coverage.response_modes,
            metrics.get("by_response_mode"),
        ),
    }
    checks: list[GateCheckResult] = []
    for group_name, (required, actual_group) in groups.items():
        for label, minimum in required.items():
            actual_count = _slice_metric(actual_group, label, "case_count", default=0)
            name = f"coverage.{group_name}.{label}"
            if actual_count >= minimum:
                checks.append(
                    GateCheckResult.pass_check(
                        name,
                        code="SLICE_COVERAGE_OK",
                        expected={"minimum": minimum},
                        actual=actual_count,
                    )
                )
            else:
                checks.append(
                    GateCheckResult.fail_check(
                        name,
                        failure_type=GateFailureType.COVERAGE_REGRESSION,
                        code="SLICE_COVERAGE_MISSING",
                        expected={"minimum": minimum},
                        actual=actual_count,
                    )
                )
    return checks


def _slice_threshold_checks(
    policy: LiveQualityGatePolicy,
    metrics: Mapping[str, Any],
) -> list[GateCheckResult]:
    groups = {
        "risk_tags": (policy.slice_thresholds.risk_tags, metrics.get("by_risk_tag")),
        "query_types": (policy.slice_thresholds.query_types, metrics.get("by_query_type")),
        "domains": (policy.slice_thresholds.domains, metrics.get("by_domain")),
        "constraint_types": (
            policy.slice_thresholds.constraint_types,
            metrics.get("by_constraint_type"),
        ),
        "response_modes": (
            policy.slice_thresholds.response_modes,
            metrics.get("by_response_mode"),
        ),
        "strategies": (policy.slice_thresholds.strategies, metrics.get("by_strategy")),
    }
    checks: list[GateCheckResult] = []
    for group_name, (thresholds, actual_group) in groups.items():
        for label, threshold in thresholds.items():
            checks.append(
                numeric_threshold_check(
                    f"slice.{group_name}.{label}.case_count",
                    _slice_metric(actual_group, label, "case_count", default=0),
                    minimum=threshold.minimum_case_count,
                    failure_type=GateFailureType.COVERAGE_REGRESSION,
                )
            )
            checks.append(
                numeric_threshold_check(
                    f"slice.{group_name}.{label}.pass_rate",
                    _slice_metric(actual_group, label, "pass_rate", default=0.0),
                    minimum=threshold.minimum_pass_rate,
                    failure_type=GateFailureType.QUALITY_REGRESSION,
                )
            )
    return checks


def _slice_metric(
    group: object,
    label: str,
    metric_name: str,
    *,
    default: Any,
) -> Any:
    if not isinstance(group, Mapping):
        return default
    summary = group.get(label)
    if not isinstance(summary, Mapping):
        return default
    return summary.get(metric_name, default)

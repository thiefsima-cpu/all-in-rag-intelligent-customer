"""Deterministic evaluation for live quality gate cases."""

from __future__ import annotations

from collections import defaultdict
from typing import Iterable, Mapping, Sequence

from rag_modules.evaluation import percentile, retrieval_metrics
from scripts.gates import GateCheckResult, GateFailureType

from .models import LiveQualityCasePolicy, LiveQualityResponseMode
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
            observation.ranked_recipe_names,
            case.relevant_recipes,
            k=top_k,
        )
        metrics = {
            "recall_at_k": retrieval["recall_at_k"],
            "mrr": retrieval["reciprocal_rank"],
            "ndcg_at_k": retrieval["ndcg_at_k"],
        }
        if _missing_positive_relevant_recipes(
            observation.ranked_recipe_names,
            case.relevant_recipes,
            top_k=top_k,
        ):
            failures.append("missing_relevant_recipes")
    else:
        metrics = dict(_EMPTY_RETRIEVAL_METRICS)
        if observation.evidence:
            failures.append("unexpected_evidence")

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
        cuisine=case.cuisine,
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
            "by_cuisine": _slice_single(grouped_results, lambda result: result.cuisine),
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


def _response_mode_passed(
    response_mode: LiveQualityResponseMode,
    observation: LiveQualityObservation,
) -> bool:
    has_evidence = bool(observation.evidence)
    if response_mode is LiveQualityResponseMode.GROUNDED_ANSWER:
        return has_evidence
    return not has_evidence


def _missing_positive_relevant_recipes(
    ranked_recipe_names: Sequence[str],
    relevant_recipes: Mapping[str, float],
    *,
    top_k: int,
) -> bool:
    positive_labels = {
        _normalize_label(recipe_name)
        for recipe_name, grade in relevant_recipes.items()
        if float(grade) > 0 and _normalize_label(recipe_name)
    }
    required_hits = min(len(positive_labels), max(0, int(top_k)))
    if required_hits <= 0:
        return False
    retrieved = set(_top_k_labels(ranked_recipe_names, top_k=top_k))
    return len(retrieved & positive_labels) < required_hits


def _top_k_labels(ranked_recipe_names: Sequence[str], *, top_k: int) -> tuple[str, ...]:
    labels: list[str] = []
    for recipe_name in ranked_recipe_names:
        label = _normalize_label(recipe_name)
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

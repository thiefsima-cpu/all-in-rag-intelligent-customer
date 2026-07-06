"""Policy loading and validation for the offline release gate."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[2]
DEFAULT_POLICY_PATH = ROOT_DIR / "eval" / "release_gate.json"


@dataclass(frozen=True)
class QualityRunnerSettings:
    profile: str
    top_k: int
    generate: bool


def load_policy(path: str | Path = DEFAULT_POLICY_PATH) -> dict[str, Any]:
    policy_path = Path(path).resolve()
    with policy_path.open("r", encoding="utf-8") as file:
        payload = json.load(file)
    if not isinstance(payload, dict):
        raise ValueError(f"Release gate policy at {policy_path} must be a JSON object.")
    schema_version = payload.get("schema_version")
    if (
        isinstance(schema_version, bool)
        or not isinstance(schema_version, int)
        or schema_version != 1
    ):
        raise ValueError(
            f"Unsupported release gate schema_version={schema_version!r}; expected integer 1."
        )
    return payload


def _required_field(policy: dict[str, Any], field_name: str) -> Any:
    if field_name not in policy:
        raise ValueError(f"Release gate policy is missing required field: {field_name}")
    return policy[field_name]


def _validate_non_empty_string_list(policy: dict[str, Any], field_name: str) -> list[str]:
    value = _required_field(policy, field_name)
    if not isinstance(value, list):
        raise ValueError(f"Release gate policy field {field_name} must be a JSON array.")
    for index, item in enumerate(value):
        if not isinstance(item, str) or not item.strip():
            raise ValueError(
                f"Release gate policy field {field_name}[{index}] must be a non-empty string."
            )
    return value


def _validate_non_negative_int(value: Any, field_name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"Release gate policy field {field_name} must be a non-negative integer.")


def _validate_rate(value: Any, field_name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(
            f"Release gate policy field {field_name} must be a finite number in [0, 1]."
        )
    numeric_value = float(value)
    if not math.isfinite(numeric_value) or numeric_value < 0.0 or numeric_value > 1.0:
        raise ValueError(
            f"Release gate policy field {field_name} must be a finite number in [0, 1]."
        )


def _validate_object(policy: dict[str, Any], field_name: str) -> dict[str, Any]:
    value = _required_field(policy, field_name)
    if not isinstance(value, dict):
        raise ValueError(f"Release gate policy field {field_name} must be a JSON object.")
    for key in value:
        if not isinstance(key, str) or not key.strip():
            raise ValueError(
                f"Release gate policy field {field_name} must use non-empty string keys."
            )
    return value


def _validate_non_negative_int_object(policy: dict[str, Any], field_name: str) -> dict[str, Any]:
    value = _validate_object(policy, field_name)
    for key, item in value.items():
        _validate_non_negative_int(item, f"{field_name}.{key}")
    return value


def _validate_rate_object(policy: dict[str, Any], field_name: str) -> dict[str, Any]:
    value = _validate_object(policy, field_name)
    for key, item in value.items():
        _validate_rate(item, f"{field_name}.{key}")
    return value


def _validate_minimums_cover_required_suites(
    value: dict[str, Any], *, field_name: str, required_suites: list[str]
) -> None:
    missing_suites = sorted(set(required_suites).difference(value))
    if missing_suites:
        joined_missing = ", ".join(missing_suites)
        raise ValueError(
            f"Release gate policy field {field_name} is missing required suites: {joined_missing}"
        )


def validate_metric_threshold_rules(metric_thresholds: Any, *, context: str) -> None:
    if not isinstance(metric_thresholds, dict):
        raise ValueError(f"{context} metric_thresholds must be a JSON object.")
    for metric_path, threshold in metric_thresholds.items():
        if not isinstance(metric_path, str) or not metric_path.strip():
            raise ValueError(f"{context} has invalid metric path.")
        if not isinstance(threshold, dict) or not {"minimum", "maximum"}.intersection(threshold):
            raise ValueError(f"{context} has invalid metric threshold rule: {metric_path}")
        for limit_name in ("minimum", "maximum"):
            if limit_name not in threshold:
                continue
            limit = threshold[limit_name]
            if isinstance(limit, bool):
                raise ValueError(
                    f"{context} has invalid metric threshold limit: {metric_path}.{limit_name}"
                )
            try:
                numeric_limit = float(limit)
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    f"{context} has invalid metric threshold limit: {metric_path}.{limit_name}"
                ) from exc
            if not math.isfinite(numeric_limit):
                raise ValueError(
                    f"{context} has invalid metric threshold limit: {metric_path}.{limit_name}"
                )


def validate_release_gate_policy(policy: dict[str, Any]) -> QualityRunnerSettings:
    required_suites = _validate_non_empty_string_list(policy, "required_suites")
    if "quality_eval" not in required_suites:
        raise ValueError("Required release-gate suite is missing: quality_eval")

    _validate_non_negative_int(
        _required_field(policy, "minimum_total_cases"),
        "minimum_total_cases",
    )
    _validate_rate(
        _required_field(policy, "minimum_overall_pass_rate"),
        "minimum_overall_pass_rate",
    )
    suite_minimum_cases = _validate_non_negative_int_object(policy, "suite_minimum_cases")
    _validate_minimums_cover_required_suites(
        suite_minimum_cases,
        field_name="suite_minimum_cases",
        required_suites=required_suites,
    )
    suite_minimum_pass_rate = _validate_rate_object(policy, "suite_minimum_pass_rate")
    _validate_minimums_cover_required_suites(
        suite_minimum_pass_rate,
        field_name="suite_minimum_pass_rate",
        required_suites=required_suites,
    )
    _validate_non_negative_int(
        _required_field(policy, "minimum_route_category_count"),
        "minimum_route_category_count",
    )
    _validate_non_empty_string_list(policy, "required_route_categories")
    _validate_non_negative_int_object(policy, "quality_dimension_minimum_cases")
    validate_metric_threshold_rules(
        _required_field(policy, "metric_thresholds"),
        context="Release gate policy",
    )
    return required_quality_stage(policy)


def required_quality_stage(policy: dict[str, Any]) -> QualityRunnerSettings:
    suite_runners = policy.get("suite_runners")
    runner = suite_runners.get("quality_eval") if isinstance(suite_runners, dict) else None
    if not isinstance(runner, dict):
        raise ValueError("Required release-gate suite has no runner: quality_eval")

    profile = runner.get("profile")
    top_k = runner.get("top_k")
    generate = runner.get("generate")
    if (
        not isinstance(profile, str)
        or not profile.strip()
        or isinstance(top_k, bool)
        or not isinstance(top_k, int)
        or top_k <= 0
        or not isinstance(generate, bool)
    ):
        raise ValueError("Required release-gate suite has invalid runner settings: quality_eval")

    return QualityRunnerSettings(
        profile=profile.strip(),
        top_k=top_k,
        generate=generate,
    )

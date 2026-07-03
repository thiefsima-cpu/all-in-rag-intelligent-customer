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
    if int(payload.get("schema_version") or 0) != 1:
        raise ValueError(
            f"Unsupported release gate schema_version={payload.get('schema_version')!r}."
        )
    return payload


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

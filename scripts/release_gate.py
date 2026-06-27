"""Run deterministic offline evaluation suites and enforce release thresholds."""

from __future__ import annotations

import argparse
import copy
import json
import os
import sys
from datetime import datetime, timezone
from functools import partial
from pathlib import Path
from typing import Any, Callable, Dict, Mapping

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from scripts.smoke_answer_pipeline import run_smoke as run_answer_pipeline
from scripts.smoke_answer_pipeline_real_route import (
    run_smoke as run_answer_pipeline_real_route,
)
from scripts.smoke_generation_plans import run_smoke as run_generation_plans
from scripts.smoke_generation_prompts import run_smoke as run_generation_prompts
from scripts.smoke_route_queries import run_smoke as run_route_semantics

ROOT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_POLICY_PATH = ROOT_DIR / "eval" / "release_gate.json"
DEFAULT_OUTPUT_DIR = ROOT_DIR / "eval" / "reports" / "release_gate"
INCLUDE_QUALITY_EVAL_ENV = "RELEASE_GATE_INCLUDE_QUALITY_EVAL"
QUALITY_EVAL_STAGE = "quality_eval"
_TRUE_ENV_VALUES = frozenset({"1", "true", "yes", "on"})
_FALSE_ENV_VALUES = frozenset({"0", "false", "no", "off"})

SuiteRunner = Callable[[], dict[str, Any]]

SUITE_RUNNERS: Dict[str, SuiteRunner] = {
    "route_semantics": run_route_semantics,
    "answer_pipeline": run_answer_pipeline,
    "answer_pipeline_real_route": run_answer_pipeline_real_route,
    "generation_plans": run_generation_plans,
    "generation_prompts": run_generation_prompts,
}


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


def _environment_flag(
    name: str,
    environ: Mapping[str, str] | None = None,
) -> bool:
    values = os.environ if environ is None else environ
    raw = values.get(name)
    if raw is None:
        return False
    normalized = raw.strip().lower()
    if normalized in _TRUE_ENV_VALUES:
        return True
    if normalized in _FALSE_ENV_VALUES:
        return False
    raise ValueError(f"Environment variable {name} must be one of 1/true/yes/on or 0/false/no/off.")


def activate_optional_stages(
    policy: dict[str, Any],
    stage_names: list[str],
) -> dict[str, Any]:
    active = copy.deepcopy(policy)
    if not stage_names:
        return active
    optional_stages = active.get("optional_stages")
    if optional_stages is None:
        optional_stages = {}
    if not isinstance(optional_stages, dict):
        raise ValueError("Release gate optional_stages must be a JSON object.")

    required_suites = list(active.get("required_suites") or [])
    minimum_cases = dict(active.get("suite_minimum_cases") or {})
    minimum_pass_rates = dict(active.get("suite_minimum_pass_rate") or {})
    metric_thresholds = dict(active.get("metric_thresholds") or {})

    for stage_name in stage_names:
        stage = optional_stages.get(stage_name)
        if not isinstance(stage, dict):
            raise ValueError(f"Optional release-gate stage is not configured: {stage_name}")
        suite_name = str(stage.get("suite") or "").strip()
        if not suite_name:
            raise ValueError(f"Optional release-gate stage has no suite: {stage_name}")
        if suite_name in required_suites:
            raise ValueError(f"Optional release-gate suite is already required: {suite_name}")

        runner = stage.get("runner")
        if not isinstance(runner, dict):
            raise ValueError(f"Optional release-gate stage has no runner object: {stage_name}")
        profile = str(runner.get("profile") or "").strip()
        top_k = int(runner.get("top_k") or 0)
        generate = runner.get("generate")
        if not profile or top_k <= 0 or not isinstance(generate, bool):
            raise ValueError(
                f"Optional release-gate stage has invalid runner settings: {stage_name}"
            )

        raw_thresholds = stage.get("metric_thresholds")
        if raw_thresholds is None:
            raw_thresholds = {}
        elif not isinstance(raw_thresholds, dict):
            raise ValueError(
                f"Optional release-gate stage has invalid metric thresholds: {stage_name}"
            )
        stage_thresholds = dict(raw_thresholds)
        duplicate_metrics = sorted(set(metric_thresholds).intersection(stage_thresholds))
        if duplicate_metrics:
            raise ValueError(
                f"Optional release-gate stage duplicates metric thresholds: {duplicate_metrics}"
            )

        required_suites.append(suite_name)
        minimum_cases[suite_name] = int(stage.get("suite_minimum_cases") or 0)
        minimum_pass_rates[suite_name] = float(stage.get("suite_minimum_pass_rate", 1.0))
        metric_thresholds.update(stage_thresholds)

    active["required_suites"] = required_suites
    active["suite_minimum_cases"] = minimum_cases
    active["suite_minimum_pass_rate"] = minimum_pass_rates
    active["metric_thresholds"] = metric_thresholds
    return active


def run_suites(
    suite_names: list[str],
    *,
    runners: Dict[str, SuiteRunner] | None = None,
) -> dict[str, dict[str, Any]]:
    resolved_runners = runners or SUITE_RUNNERS
    reports: dict[str, dict[str, Any]] = {}
    for suite_name in suite_names:
        runner = resolved_runners.get(suite_name)
        if runner is None:
            reports[suite_name] = {
                "case_count": 0,
                "passed_count": 0,
                "results": [],
                "failures": [{"suite_error": f"unknown_suite:{suite_name}"}],
                "suite_error": f"unknown_suite:{suite_name}",
            }
            continue
        try:
            report = runner()
            reports[suite_name] = dict(report or {})
        except Exception as exc:
            reports[suite_name] = {
                "case_count": 0,
                "passed_count": 0,
                "results": [],
                "failures": [{"suite_error": f"{type(exc).__name__}: {exc}"}],
                "suite_error": f"{type(exc).__name__}: {exc}",
            }
    return reports


def _run_quality_eval(stage: dict[str, Any]) -> dict[str, Any]:
    from scripts.eval_queries import evaluate_queries

    runner = dict(stage.get("runner") or {})
    report = evaluate_queries(
        top_k=int(runner.get("top_k") or 3),
        generate=bool(runner.get("generate", False)),
        profile=str(runner.get("profile") or "") or None,
    )
    metrics = dict(report.get("metrics") or {})
    results = [dict(item) for item in (report.get("results") or [])]
    failures = [dict(item) for item in (report.get("failures") or [])]
    case_count = max(0, int(metrics.get("case_count") or len(results)))
    passed_count = sum(1 for item in results if item.get("passed"))
    return {
        "case_count": case_count,
        "passed_count": min(case_count, passed_count),
        "metrics": metrics,
        "results": results,
        "failures": failures,
        "profile": dict(report.get("profile") or {}),
    }


def _suite_metrics(report: dict[str, Any]) -> dict[str, Any]:
    case_count = max(0, int(report.get("case_count") or 0))
    passed_count = max(0, int(report.get("passed_count") or 0))
    passed_count = min(case_count, passed_count)
    pass_rate = passed_count / case_count if case_count else 0.0
    return {
        "case_count": case_count,
        "passed_count": passed_count,
        "failed_count": case_count - passed_count,
        "pass_rate": pass_rate,
        "suite_error": str(report.get("suite_error") or ""),
    }


def _check(
    checks: list[dict[str, Any]],
    *,
    name: str,
    passed: bool,
    expected: Any,
    actual: Any,
) -> None:
    checks.append(
        {
            "name": name,
            "passed": bool(passed),
            "expected": expected,
            "actual": actual,
        }
    )


def _resolve_metric(
    suite_reports: dict[str, dict[str, Any]],
    path: str,
) -> Any:
    parts = [part for part in str(path or "").split(".") if part]
    if len(parts) < 2:
        return None
    current: Any = suite_reports.get(parts[0])
    for part in parts[1:]:
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


def _evaluate_metric_thresholds(
    checks: list[dict[str, Any]],
    *,
    policy: dict[str, Any],
    suite_reports: dict[str, dict[str, Any]],
) -> None:
    for metric_path, threshold in dict(policy.get("metric_thresholds") or {}).items():
        limits = dict(threshold or {})
        actual = _resolve_metric(suite_reports, str(metric_path))
        if actual is None:
            _check(
                checks,
                name=f"metric_available:{metric_path}",
                passed=False,
                expected="numeric_metric",
                actual=None,
            )
            continue
        try:
            numeric_actual = float(actual)
        except (TypeError, ValueError):
            _check(
                checks,
                name=f"metric_numeric:{metric_path}",
                passed=False,
                expected="numeric_metric",
                actual=actual,
            )
            continue
        if "minimum" in limits:
            minimum = float(limits["minimum"])
            _check(
                checks,
                name=f"metric_minimum:{metric_path}",
                passed=numeric_actual >= minimum,
                expected=f">={minimum}",
                actual=numeric_actual,
            )
        if "maximum" in limits:
            maximum = float(limits["maximum"])
            _check(
                checks,
                name=f"metric_maximum:{metric_path}",
                passed=numeric_actual <= maximum,
                expected=f"<={maximum}",
                actual=numeric_actual,
            )


def evaluate_gate(
    policy: dict[str, Any],
    suite_reports: dict[str, dict[str, Any]],
    *,
    generated_at: str | None = None,
) -> dict[str, Any]:
    required_suites = [
        str(item) for item in (policy.get("required_suites") or []) if str(item).strip()
    ]
    minimum_cases = {
        str(key): max(0, int(value))
        for key, value in dict(policy.get("suite_minimum_cases") or {}).items()
    }
    minimum_pass_rates = {
        str(key): float(value)
        for key, value in dict(policy.get("suite_minimum_pass_rate") or {}).items()
    }

    suite_metrics = {
        suite_name: _suite_metrics(suite_reports.get(suite_name) or {})
        for suite_name in required_suites
    }
    checks: list[dict[str, Any]] = []

    for suite_name in required_suites:
        metrics = suite_metrics[suite_name]
        suite_present = suite_name in suite_reports and not metrics["suite_error"]
        _check(
            checks,
            name=f"suite_available:{suite_name}",
            passed=suite_present,
            expected="available_without_error",
            actual=metrics["suite_error"]
            or ("available" if suite_name in suite_reports else "missing"),
        )

        required_case_count = minimum_cases.get(suite_name, 0)
        _check(
            checks,
            name=f"suite_case_count:{suite_name}",
            passed=metrics["case_count"] >= required_case_count,
            expected=f">={required_case_count}",
            actual=metrics["case_count"],
        )

        required_pass_rate = minimum_pass_rates.get(suite_name, 1.0)
        _check(
            checks,
            name=f"suite_pass_rate:{suite_name}",
            passed=metrics["pass_rate"] >= required_pass_rate,
            expected=f">={required_pass_rate}",
            actual=metrics["pass_rate"],
        )

    total_cases = sum(item["case_count"] for item in suite_metrics.values())
    total_passed = sum(item["passed_count"] for item in suite_metrics.values())
    overall_pass_rate = total_passed / total_cases if total_cases else 0.0
    minimum_total_cases = max(0, int(policy.get("minimum_total_cases") or 0))
    minimum_overall_pass_rate = float(policy.get("minimum_overall_pass_rate", 1.0))
    _check(
        checks,
        name="minimum_total_cases",
        passed=total_cases >= minimum_total_cases,
        expected=f">={minimum_total_cases}",
        actual=total_cases,
    )
    _check(
        checks,
        name="minimum_overall_pass_rate",
        passed=overall_pass_rate >= minimum_overall_pass_rate,
        expected=f">={minimum_overall_pass_rate}",
        actual=overall_pass_rate,
    )

    route_report = suite_reports.get("route_semantics") or {}
    route_categories = dict(route_report.get("category_counts") or {})
    minimum_route_category_count = max(
        0,
        int(policy.get("minimum_route_category_count") or 0),
    )
    _check(
        checks,
        name="minimum_route_category_count",
        passed=len(route_categories) >= minimum_route_category_count,
        expected=f">={minimum_route_category_count}",
        actual=len(route_categories),
    )
    required_route_categories = {
        str(item) for item in (policy.get("required_route_categories") or []) if str(item).strip()
    }
    missing_route_categories = sorted(required_route_categories.difference(route_categories))
    _check(
        checks,
        name="required_route_categories",
        passed=not missing_route_categories,
        expected=sorted(required_route_categories),
        actual={
            "present": sorted(route_categories),
            "missing": missing_route_categories,
        },
    )
    _evaluate_metric_thresholds(
        checks,
        policy=policy,
        suite_reports=suite_reports,
    )

    failed_checks = [item for item in checks if not item["passed"]]
    return {
        "generated_at": generated_at or datetime.now(timezone.utc).isoformat(),
        "passed": not failed_checks,
        "metrics": {
            "suite_count": len(required_suites),
            "case_count": total_cases,
            "passed_count": total_passed,
            "failed_count": total_cases - total_passed,
            "pass_rate": overall_pass_rate,
            "route_category_count": len(route_categories),
        },
        "suite_metrics": suite_metrics,
        "checks": checks,
        "failed_checks": failed_checks,
        "suite_reports": {
            suite_name: suite_reports.get(suite_name) or {} for suite_name in required_suites
        },
    }


def write_report(
    report: dict[str, Any],
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
) -> tuple[Path, Path]:
    resolved_output_dir = Path(output_dir).resolve()
    resolved_output_dir.mkdir(parents=True, exist_ok=True)
    report_path = resolved_output_dir / "report.json"
    summary_path = resolved_output_dir / "summary.md"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    metrics = report.get("metrics") or {}
    status = "PASS" if report.get("passed") else "FAIL"
    optional_stages = [str(item) for item in (report.get("included_optional_stages") or [])]
    optional_stage_label = ", ".join(optional_stages) if optional_stages else "none"
    lines = [
        "# Offline Evaluation Release Gate",
        "",
        f"- status: {status}",
        f"- generated_at: {report.get('generated_at', '')}",
        f"- optional_stages: {optional_stage_label}",
        f"- suites: {metrics.get('suite_count', 0)}",
        f"- cases: {metrics.get('passed_count', 0)}/{metrics.get('case_count', 0)}",
        f"- pass_rate: {metrics.get('pass_rate', 0.0):.4f}",
        f"- route_categories: {metrics.get('route_category_count', 0)}",
        "",
        "## Suites",
        "",
        "| Suite | Passed | Cases | Pass rate |",
        "| --- | ---: | ---: | ---: |",
    ]
    for suite_name, suite in (report.get("suite_metrics") or {}).items():
        lines.append(
            f"| {suite_name} | {suite.get('passed_count', 0)} | "
            f"{suite.get('case_count', 0)} | {suite.get('pass_rate', 0.0):.4f} |"
        )
    failed_checks = report.get("failed_checks") or []
    if failed_checks:
        lines.extend(["", "## Failed Checks", ""])
        for item in failed_checks:
            lines.append(
                f"- `{item.get('name', '')}` expected "
                f"`{item.get('expected')}`; actual `{item.get('actual')}`"
            )
    summary_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report_path, summary_path


def run_release_gate(
    *,
    policy_path: str | Path = DEFAULT_POLICY_PATH,
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
    include_quality_eval: bool = False,
) -> dict[str, Any]:
    resolved_policy_path = Path(policy_path).resolve()
    policy = load_policy(policy_path)
    included_optional_stages = [QUALITY_EVAL_STAGE] if include_quality_eval else []
    try:
        active_policy = activate_optional_stages(policy, included_optional_stages)
    except ValueError as exc:
        raise ValueError(f"Invalid release gate policy at {resolved_policy_path}: {exc}") from exc

    required_suites = [
        str(item) for item in (active_policy.get("required_suites") or []) if str(item).strip()
    ]
    runners = dict(SUITE_RUNNERS)
    if include_quality_eval:
        stage = active_policy["optional_stages"][QUALITY_EVAL_STAGE]
        suite_name = str(stage["suite"])
        runners[suite_name] = partial(_run_quality_eval, stage)
    suite_reports = run_suites(required_suites, runners=runners)
    report = evaluate_gate(active_policy, suite_reports)
    report["included_optional_stages"] = included_optional_stages
    report["policy_path"] = str(resolved_policy_path)
    report_path, summary_path = write_report(report, output_dir)
    report["report_path"] = str(report_path)
    report["summary_path"] = str(summary_path)
    return report


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")

    parser = argparse.ArgumentParser()
    parser.add_argument("--policy", default=str(DEFAULT_POLICY_PATH))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--json", action="store_true")
    parser.add_argument(
        "--include-quality-eval",
        action="store_true",
        help="Include the policy-configured quality evaluation stage.",
    )
    args = parser.parse_args()

    try:
        environment_requested = _environment_flag(INCLUDE_QUALITY_EVAL_ENV)
    except ValueError as exc:
        parser.error(str(exc))

    report = run_release_gate(
        policy_path=args.policy,
        output_dir=args.output_dir,
        include_quality_eval=args.include_quality_eval or environment_requested,
    )
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        metrics = report["metrics"]
        status = "PASS" if report["passed"] else "FAIL"
        print(
            f"[{status}] offline release gate "
            f"cases={metrics['passed_count']}/{metrics['case_count']} "
            f"pass_rate={metrics['pass_rate']:.4f} "
            f"route_categories={metrics['route_category_count']}"
        )
        for suite_name, suite in report["suite_metrics"].items():
            print(
                f"  {suite_name}: "
                f"{suite['passed_count']}/{suite['case_count']} "
                f"pass_rate={suite['pass_rate']:.4f}"
            )
        for check in report["failed_checks"]:
            print(
                f"  failed_check={check['name']} "
                f"expected={check['expected']} actual={check['actual']}"
            )
        print(f"report={report['report_path']}")
        print(f"summary={report['summary_path']}")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

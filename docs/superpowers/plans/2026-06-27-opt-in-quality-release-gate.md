# Opt-in Quality Evaluation Release Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep the default release gate as the existing deterministic smoke check while allowing the configured quality evaluation to join it through one CLI flag or environment variable.

**Architecture:** Extract a reusable structured-report function from `scripts/eval_queries.py`, then adapt that report to the existing release-gate suite contract. Treat `quality_eval` as a policy-defined optional stage: activation produces a copied active policy, injects a lazy runner, and feeds the resulting suite through the existing checks and reports.

**Tech Stack:** Python 3.11, `argparse`, JSON policy, `unittest`/pytest, `unittest.mock`, existing GraphRAG evaluation runtime.

---

## File Map

- Modify `scripts/eval_queries.py`: expose a report-returning evaluation function while preserving the current CLI wrapper.
- Modify `scripts/release_gate.py`: parse opt-in state, activate the optional policy stage, adapt the quality report, and expose stage state in reports.
- Modify `eval/release_gate.json`: define the optional quality runner settings and thresholds.
- Modify `tests/test_eval_queries.py`: cover the extracted report function and the unchanged CLI wrapper contract.
- Modify `tests/test_release_gate.py`: cover policy activation, environment parsing, runner normalization, thresholds, CLI wiring, and reporting.
- Modify `docs/offline_evaluation_release_gate.md`: document default smoke behavior, both opt-in mechanisms, and thresholds.
- Modify `README.md`: add the one-command quality-gate invocation beside the default release-gate command.

### Task 1: Extract a Structured Quality Evaluation Function

**Files:**
- Modify: `scripts/eval_queries.py:580-659`
- Test: `tests/test_eval_queries.py:1-257`

- [ ] **Step 1: Write the failing structured-report test**

Add `io`, `redirect_stdout`, `MagicMock`, and `patch` imports; import `evaluate_queries` and
`run_eval`; then add these tests to `EvalQueriesTests`:

```python
import io
from contextlib import redirect_stdout
from unittest.mock import MagicMock, patch

from scripts.eval_queries import (
    DEFAULT_CORPUS_PATH,
    EvalCase,
    build_eval_report,
    evaluate_case,
    evaluate_queries,
    load_eval_cases,
    run_eval,
)


def test_evaluate_queries_returns_report_and_closes_system(self) -> None:
    config = build_test_config()
    config.profile_name = "eval_quality"
    case = EvalCase(query="quality query")
    item = {"query": case.query, "passed": True, "failures": []}
    system = MagicMock()

    with (
        patch("scripts.eval_queries.load_eval_cases", return_value=[case]),
        patch("scripts.eval_queries.load_config", return_value=config) as load_config_mock,
        patch("scripts.eval_queries.AdvancedGraphRAGSystem", return_value=system),
        patch("scripts.eval_queries.evaluate_case", return_value=item),
        patch(
            "scripts.eval_queries.calculate_eval_metrics",
            return_value={"case_count": 1, "pass_rate": 1.0},
        ),
    ):
        report = evaluate_queries(
            top_k=6,
            generate=True,
            profile="eval_quality",
        )

    load_config_mock.assert_called_once_with(profile="eval_quality", profile_path=None)
    system.initialize_system.assert_called_once_with()
    system.build_knowledge_base.assert_called_once_with()
    system.close.assert_called_once_with()
    self.assertEqual(report["metrics"]["case_count"], 1)
    self.assertEqual(report["results"], [item])
    self.assertEqual(report["failures"], [])
    self.assertEqual(report["profile"]["name"], "eval_quality")
    self.assertTrue(report["generate"])


def test_run_eval_preserves_json_output_and_failure_exit_code(self) -> None:
    failed_item = {"query": "quality query", "passed": False, "failures": ["no_evidence"]}
    report = {
        "profile": {"name": "eval_quality"},
        "metrics": {"case_count": 1, "pass_rate": 0.0},
        "results": [failed_item],
        "failures": [failed_item],
    }
    stdout = io.StringIO()

    with (
        patch("scripts.eval_queries.evaluate_queries", return_value=report),
        redirect_stdout(stdout),
    ):
        exit_code = run_eval(
            top_k=6,
            as_json=True,
            generate=True,
            profile="eval_quality",
        )

    self.assertEqual(exit_code, 1)
    self.assertEqual(json.loads(stdout.getvalue()), report)
```

Also add `import json` at the top of the test module.

- [ ] **Step 2: Run the new test and verify RED**

Run:

```powershell
python -m pytest tests/test_eval_queries.py -k "evaluate_queries_returns_report or run_eval_preserves" -q
```

Expected: collection fails because `scripts.eval_queries` does not export `evaluate_queries`.

- [ ] **Step 3: Extract the minimal report function**

Insert this function above `run_eval()` and move the existing evaluation body into it:

```python
def evaluate_queries(
    *,
    top_k: int,
    generate: bool,
    corpus_path: str | Path = DEFAULT_CORPUS_PATH,
    profile: str | None = None,
    profile_path: str | None = None,
) -> dict[str, Any]:
    cases = load_eval_cases(corpus_path)
    config = load_config(profile=profile, profile_path=profile_path)
    system = AdvancedGraphRAGSystem(config=config)
    system.initialize_system()
    system.build_knowledge_base()

    failures: list[dict[str, Any]] = []
    results: list[dict[str, Any]] = []
    try:
        for case in cases:
            item = evaluate_case(
                system,
                case,
                top_k=top_k,
                generate=generate,
            )
            results.append(item)
            if not item["passed"]:
                failures.append(item)
    finally:
        system.close()

    return build_eval_report(
        metrics=calculate_eval_metrics(results),
        results=results,
        failures=failures,
        config=config,
        corpus_path=corpus_path,
        top_k=top_k,
        generate=generate,
    )
```

Replace the duplicated setup/evaluation block at the start of `run_eval()` with:

```python
    report = evaluate_queries(
        top_k=top_k,
        generate=generate,
        corpus_path=corpus_path,
        profile=profile,
        profile_path=profile_path,
    )
    results = list(report["results"])
    failures = list(report["failures"])
```

Keep the existing file writing, console rendering, and exit-code logic below those assignments.

- [ ] **Step 4: Verify GREEN and the existing evaluation tests**

Run:

```powershell
python -m pytest tests/test_eval_queries.py tests/test_evaluation_metrics.py -q
```

Expected: all tests pass.

- [ ] **Step 5: Commit the extraction**

```powershell
git add scripts/eval_queries.py tests/test_eval_queries.py
git commit -m "refactor: expose structured quality evaluation report"
```

### Task 2: Put the Optional Quality Stage in the Default Policy

**Files:**
- Modify: `eval/release_gate.json`
- Test: `tests/test_release_gate.py:42-53`

- [ ] **Step 1: Write the failing default-policy test**

Add this test to `ReleaseGateTests`:

```python
def test_default_policy_configures_quality_eval_as_optional(self) -> None:
    policy = load_policy(DEFAULT_POLICY_PATH)

    self.assertNotIn("quality_eval", policy["required_suites"])
    stage = policy["optional_stages"]["quality_eval"]
    self.assertEqual(stage["suite"], "quality_eval")
    self.assertEqual(
        stage["runner"],
        {"profile": "eval_quality", "top_k": 6, "generate": True},
    )
    self.assertEqual(stage["suite_minimum_cases"], 6)
    self.assertEqual(stage["suite_minimum_pass_rate"], 1.0)
    self.assertEqual(
        stage["metric_thresholds"],
        {
            "quality_eval.metrics.recall_at_k": {"minimum": 0.8},
            "quality_eval.metrics.faithfulness": {"minimum": 0.8},
            "quality_eval.metrics.citation_accuracy": {"minimum": 0.8},
            "quality_eval.metrics.p95_latency_ms": {"maximum": 2000.0},
            "quality_eval.metrics.estimated_cost_usd": {"maximum": 1.0},
        },
    )
```

- [ ] **Step 2: Run the policy test and verify RED**

Run:

```powershell
python -m pytest tests/test_release_gate.py::ReleaseGateTests::test_default_policy_configures_quality_eval_as_optional -q
```

Expected: FAIL with `KeyError: 'optional_stages'`.

- [ ] **Step 3: Add the optional stage to the JSON policy**

Add this top-level object after the current `metric_thresholds` object, preserving valid JSON:

```json
"optional_stages": {
  "quality_eval": {
    "suite": "quality_eval",
    "runner": {
      "profile": "eval_quality",
      "top_k": 6,
      "generate": true
    },
    "suite_minimum_cases": 6,
    "suite_minimum_pass_rate": 1.0,
    "metric_thresholds": {
      "quality_eval.metrics.recall_at_k": {"minimum": 0.8},
      "quality_eval.metrics.faithfulness": {"minimum": 0.8},
      "quality_eval.metrics.citation_accuracy": {"minimum": 0.8},
      "quality_eval.metrics.p95_latency_ms": {"maximum": 2000.0},
      "quality_eval.metrics.estimated_cost_usd": {"maximum": 1.0}
    }
  }
}
```

- [ ] **Step 4: Verify GREEN and the unchanged default gate contract**

Run:

```powershell
python -m pytest tests/test_release_gate.py::ReleaseGateTests::test_default_policy_configures_quality_eval_as_optional tests/test_release_gate.py::ReleaseGateTests::test_default_offline_release_gate_passes -q
```

Expected: both tests pass; the default report still has 39 cases.

- [ ] **Step 5: Commit the policy**

```powershell
git add eval/release_gate.json tests/test_release_gate.py
git commit -m "feat: configure optional quality release stage"
```

### Task 3: Activate Optional Stages Without Mutating Policy

**Files:**
- Modify: `scripts/release_gate.py:10-48`
- Modify: `scripts/release_gate.py:133-166`
- Test: `tests/test_release_gate.py`

- [ ] **Step 1: Write failing environment and activation tests**

Add `copy` and `os` imports, import the new symbols, and add these tests:

```python
import copy
import os

from scripts.release_gate import (
    DEFAULT_POLICY_PATH,
    INCLUDE_QUALITY_EVAL_ENV,
    _environment_flag,
    activate_optional_stages,
    evaluate_gate,
    load_policy,
    run_suites,
    write_report,
)


def test_environment_flag_accepts_explicit_boolean_spellings(self) -> None:
    for value in ("1", "true", "TRUE", "yes", "on"):
        with self.subTest(value=value):
            self.assertTrue(_environment_flag(INCLUDE_QUALITY_EVAL_ENV, {INCLUDE_QUALITY_EVAL_ENV: value}))
    for value in ("0", "false", "FALSE", "no", "off"):
        with self.subTest(value=value):
            self.assertFalse(
                _environment_flag(INCLUDE_QUALITY_EVAL_ENV, {INCLUDE_QUALITY_EVAL_ENV: value})
            )
    self.assertFalse(_environment_flag(INCLUDE_QUALITY_EVAL_ENV, {}))


def test_environment_flag_rejects_ambiguous_values(self) -> None:
    with self.assertRaisesRegex(ValueError, INCLUDE_QUALITY_EVAL_ENV):
        _environment_flag(INCLUDE_QUALITY_EVAL_ENV, {INCLUDE_QUALITY_EVAL_ENV: "sometimes"})


def test_activate_quality_stage_copies_and_merges_policy(self) -> None:
    policy = load_policy(DEFAULT_POLICY_PATH)
    original = copy.deepcopy(policy)

    active = activate_optional_stages(policy, ["quality_eval"])

    self.assertEqual(policy, original)
    self.assertEqual(active["required_suites"][-1], "quality_eval")
    self.assertEqual(active["suite_minimum_cases"]["quality_eval"], 6)
    self.assertEqual(active["suite_minimum_pass_rate"]["quality_eval"], 1.0)
    self.assertEqual(
        active["metric_thresholds"]["quality_eval.metrics.recall_at_k"],
        {"minimum": 0.8},
    )


def test_activate_quality_stage_requires_policy_configuration(self) -> None:
    policy = load_policy(DEFAULT_POLICY_PATH)
    policy.pop("optional_stages")

    with self.assertRaisesRegex(ValueError, "quality_eval"):
        activate_optional_stages(policy, ["quality_eval"])


def test_activate_optional_stages_leaves_unselected_legacy_policy_unchanged(self) -> None:
    policy = load_policy(DEFAULT_POLICY_PATH)
    policy.pop("optional_stages")

    self.assertEqual(activate_optional_stages(policy, []), policy)


def test_activate_quality_stage_rejects_collisions_and_malformed_runner(self) -> None:
    duplicate_suite = load_policy(DEFAULT_POLICY_PATH)
    duplicate_suite["optional_stages"]["quality_eval"]["suite"] = "route_semantics"
    with self.assertRaisesRegex(ValueError, "already required"):
        activate_optional_stages(duplicate_suite, ["quality_eval"])

    duplicate_metric = load_policy(DEFAULT_POLICY_PATH)
    duplicate_metric["optional_stages"]["quality_eval"]["metric_thresholds"] = {
        "answer_pipeline_real_route.metrics.plan_contract_pass_rate": {"minimum": 1.0}
    }
    with self.assertRaisesRegex(ValueError, "duplicates metric thresholds"):
        activate_optional_stages(duplicate_metric, ["quality_eval"])

    malformed_runner = load_policy(DEFAULT_POLICY_PATH)
    malformed_runner["optional_stages"]["quality_eval"]["runner"] = {"top_k": 0}
    with self.assertRaisesRegex(ValueError, "runner"):
        activate_optional_stages(malformed_runner, ["quality_eval"])
```

- [ ] **Step 2: Run the tests and verify RED**

Run:

```powershell
python -m pytest tests/test_release_gate.py -k "environment_flag or activate_quality_stage" -q
```

Expected: collection fails because the imported constant and functions do not exist.

- [ ] **Step 3: Implement strict environment parsing**

Add `copy` and `Mapping` imports, constants, and this helper near the release-gate constants:

```python
import copy
from typing import Any, Callable, Dict, Mapping

INCLUDE_QUALITY_EVAL_ENV = "RELEASE_GATE_INCLUDE_QUALITY_EVAL"
QUALITY_EVAL_STAGE = "quality_eval"
_TRUE_ENV_VALUES = frozenset({"1", "true", "yes", "on"})
_FALSE_ENV_VALUES = frozenset({"0", "false", "no", "off"})


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
    raise ValueError(
        f"Environment variable {name} must be one of "
        "1/true/yes/on or 0/false/no/off."
    )
```

- [ ] **Step 4: Implement copied policy activation**

Add this function after `load_policy()`:

```python
def activate_optional_stages(
    policy: dict[str, Any],
    stage_names: list[str],
) -> dict[str, Any]:
    active = copy.deepcopy(policy)
    if not stage_names:
        return active
    optional_stages = active.get("optional_stages") or {}
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

        raw_thresholds = stage.get("metric_thresholds") or {}
        if not isinstance(raw_thresholds, dict):
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
        minimum_pass_rates[suite_name] = float(
            stage.get("suite_minimum_pass_rate", 1.0)
        )
        metric_thresholds.update(stage_thresholds)

    active["required_suites"] = required_suites
    active["suite_minimum_cases"] = minimum_cases
    active["suite_minimum_pass_rate"] = minimum_pass_rates
    active["metric_thresholds"] = metric_thresholds
    return active
```

- [ ] **Step 5: Verify GREEN**

Run:

```powershell
python -m pytest tests/test_release_gate.py -k "environment_flag or activate_quality_stage" -q
```

Expected: all selected tests pass.

- [ ] **Step 6: Commit activation behavior**

```powershell
git add scripts/release_gate.py tests/test_release_gate.py
git commit -m "feat: activate optional release gate stages"
```

### Task 4: Adapt and Run the Quality Suite on Opt-in

**Files:**
- Modify: `scripts/release_gate.py:344-364`
- Test: `tests/test_release_gate.py`

- [ ] **Step 1: Add synthetic quality report helpers and failing adapter test**

Import `_run_quality_eval` and add these helpers and test:

```python
from unittest.mock import patch

from scripts.release_gate import _run_quality_eval


def _quality_metrics() -> dict:
    return {
        "case_count": 6,
        "pass_rate": 1.0,
        "recall_at_k": 0.8,
        "faithfulness": 0.8,
        "citation_accuracy": 0.8,
        "p95_latency_ms": 2000.0,
        "estimated_cost_usd": 1.0,
    }


def _quality_suite_report() -> dict:
    return {
        "case_count": 6,
        "passed_count": 6,
        "metrics": _quality_metrics(),
        "results": [{"query": str(index), "passed": True} for index in range(6)],
        "failures": [],
    }


def _passing_reports_for_policy(policy: dict) -> dict:
    return {
        "route_semantics": {
            **_suite_report(24),
            "category_counts": {
                category: 1 for category in policy["required_route_categories"]
            },
        },
        "answer_pipeline": _suite_report(3),
        "answer_pipeline_real_route": _real_route_suite_report(3),
        "generation_plans": _suite_report(3),
        "generation_prompts": _suite_report(6),
        "quality_eval": _quality_suite_report(),
    }


def test_quality_runner_normalizes_structured_eval_report(self) -> None:
    eval_report = {
        "metrics": _quality_metrics(),
        "results": [{"query": str(index), "passed": True} for index in range(6)],
        "failures": [],
        "profile": {"name": "eval_quality"},
    }
    stage = load_policy(DEFAULT_POLICY_PATH)["optional_stages"]["quality_eval"]

    with patch("scripts.eval_queries.evaluate_queries", return_value=eval_report) as evaluate:
        report = _run_quality_eval(stage)

    evaluate.assert_called_once_with(
        top_k=6,
        generate=True,
        profile="eval_quality",
    )
    self.assertEqual(report["case_count"], 6)
    self.assertEqual(report["passed_count"], 6)
    self.assertEqual(report["metrics"]["recall_at_k"], 0.8)
    self.assertEqual(report["profile"], {"name": "eval_quality"})
```

- [ ] **Step 2: Run the adapter test and verify RED**

Run:

```powershell
python -m pytest tests/test_release_gate.py::ReleaseGateTests::test_quality_runner_normalizes_structured_eval_report -q
```

Expected: collection fails because `_run_quality_eval` does not exist.

- [ ] **Step 3: Implement the lazy quality adapter**

Add this helper below `run_suites()`:

```python
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
```

- [ ] **Step 4: Verify the adapter test passes**

Run:

```powershell
python -m pytest tests/test_release_gate.py::ReleaseGateTests::test_quality_runner_normalizes_structured_eval_report -q
```

Expected: PASS.

- [ ] **Step 5: Write the failing opted-in orchestration test**

Add this test, using the existing suite-report helpers:

```python
def test_run_release_gate_includes_quality_suite_only_when_requested(self) -> None:
    policy = load_policy(DEFAULT_POLICY_PATH)
    suite_reports = {
        "route_semantics": {
            **_suite_report(24),
            "category_counts": {
                category: 1 for category in policy["required_route_categories"]
            },
        },
        "answer_pipeline": _suite_report(3),
        "answer_pipeline_real_route": _real_route_suite_report(3),
        "generation_plans": _suite_report(3),
        "generation_prompts": _suite_report(6),
        "quality_eval": _quality_suite_report(),
    }

    with tempfile.TemporaryDirectory() as temp_dir:
        with patch("scripts.release_gate.run_suites", return_value=suite_reports) as run:
            report = run_release_gate(
                output_dir=temp_dir,
                include_quality_eval=True,
            )

    suite_names = run.call_args.args[0]
    self.assertIn("quality_eval", suite_names)
    self.assertIn("quality_eval", run.call_args.kwargs["runners"])
    self.assertEqual(report["included_optional_stages"], ["quality_eval"])
    self.assertEqual(report["metrics"]["suite_count"], 6)
    self.assertEqual(report["metrics"]["case_count"], 45)
    self.assertTrue(report["passed"])


def test_run_release_gate_default_does_not_register_quality_runner(self) -> None:
    policy = load_policy(DEFAULT_POLICY_PATH)
    suite_reports = _passing_reports_for_policy(policy)
    suite_reports.pop("quality_eval")

    with tempfile.TemporaryDirectory() as temp_dir:
        with patch("scripts.release_gate.run_suites", return_value=suite_reports) as run:
            report = run_release_gate(output_dir=temp_dir)

    self.assertNotIn("quality_eval", run.call_args.args[0])
    self.assertNotIn("quality_eval", run.call_args.kwargs["runners"])
    self.assertEqual(report["included_optional_stages"], [])
    self.assertEqual(report["metrics"]["case_count"], 39)


def test_quality_runner_failure_becomes_failed_suite_report(self) -> None:
    def fail_quality_eval() -> dict:
        raise RuntimeError("quality backend unavailable")

    reports = run_suites(
        ["quality_eval"],
        runners={"quality_eval": fail_quality_eval},
    )

    self.assertIn("RuntimeError: quality backend unavailable", reports["quality_eval"]["suite_error"])


def test_run_release_gate_policy_error_includes_policy_path(self) -> None:
    policy = load_policy(DEFAULT_POLICY_PATH)
    policy["optional_stages"]["quality_eval"]["runner"] = {}

    with tempfile.TemporaryDirectory() as temp_dir:
        policy_path = Path(temp_dir) / "release_gate.json"
        policy_path.write_text(json.dumps(policy), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, re.escape(str(policy_path.resolve()))):
            run_release_gate(
                policy_path=policy_path,
                output_dir=temp_dir,
                include_quality_eval=True,
            )
```

Also import `json`, `re`, `Path`, and `run_release_gate` in the test module.

- [ ] **Step 6: Run the orchestration test and verify RED**

Run:

```powershell
python -m pytest tests/test_release_gate.py::ReleaseGateTests::test_run_release_gate_includes_quality_suite_only_when_requested -q
```

Expected: FAIL because `run_release_gate()` does not accept `include_quality_eval`.

- [ ] **Step 7: Wire stage activation and runner injection into `run_release_gate()`**

Add `partial` to the imports and replace `run_release_gate()` with:

```python
from functools import partial


def run_release_gate(
    *,
    policy_path: str | Path = DEFAULT_POLICY_PATH,
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
    include_quality_eval: bool = False,
) -> dict[str, Any]:
    policy = load_policy(policy_path)
    included_optional_stages = [QUALITY_EVAL_STAGE] if include_quality_eval else []
    try:
        active_policy = activate_optional_stages(policy, included_optional_stages)
    except ValueError as exc:
        resolved_policy_path = Path(policy_path).resolve()
        raise ValueError(f"Invalid release gate policy at {resolved_policy_path}: {exc}") from exc
    required_suites = [
        str(item)
        for item in (active_policy.get("required_suites") or [])
        if str(item).strip()
    ]
    runners = dict(SUITE_RUNNERS)
    if include_quality_eval:
        stage = active_policy["optional_stages"][QUALITY_EVAL_STAGE]
        suite_name = str(stage["suite"])
        runners[suite_name] = partial(_run_quality_eval, stage)

    suite_reports = run_suites(required_suites, runners=runners)
    report = evaluate_gate(active_policy, suite_reports)
    report["included_optional_stages"] = included_optional_stages
    report["policy_path"] = str(Path(policy_path).resolve())
    report_path, summary_path = write_report(report, output_dir)
    report["report_path"] = str(report_path)
    report["summary_path"] = str(summary_path)
    return report
```

- [ ] **Step 8: Verify orchestration and default behavior**

Run:

```powershell
python -m pytest tests/test_release_gate.py -k "run_release_gate_includes_quality or default_does_not_register or quality_runner_failure or default_offline" -q
```

Expected: both tests pass; the default test remains at 39 cases.

- [ ] **Step 9: Commit quality-suite execution**

```powershell
git add scripts/release_gate.py tests/test_release_gate.py
git commit -m "feat: run quality evaluation on release gate opt-in"
```

### Task 5: Enforce Quality Thresholds and Wire CLI/Reports

**Files:**
- Modify: `scripts/release_gate.py:133-166`
- Modify: `scripts/release_gate.py:300-416`
- Test: `tests/test_release_gate.py`

- [ ] **Step 1: Write failing boundary and invalid-metric tests**

Add these tests using the module-level `_passing_reports_for_policy()` helper:

```python
def test_quality_thresholds_pass_at_boundaries_and_fail_outside_them(self) -> None:
    policy = activate_optional_stages(load_policy(DEFAULT_POLICY_PATH), ["quality_eval"])
    boundary_report = evaluate_gate(policy, _passing_reports_for_policy(policy))
    self.assertTrue(boundary_report["passed"])

    failing_values = {
        "recall_at_k": 0.79,
        "faithfulness": 0.79,
        "citation_accuracy": 0.79,
        "p95_latency_ms": 2000.1,
        "estimated_cost_usd": 1.01,
    }
    for metric_name, failing_value in failing_values.items():
        with self.subTest(metric=metric_name):
            reports = _passing_reports_for_policy(policy)
            reports["quality_eval"]["metrics"][metric_name] = failing_value
            report = evaluate_gate(policy, reports)
            self.assertFalse(report["passed"])
            self.assertTrue(
                any(metric_name in check["name"] for check in report["failed_checks"])
            )


def test_gate_reports_non_numeric_quality_metric_as_failed_check(self) -> None:
    policy = activate_optional_stages(load_policy(DEFAULT_POLICY_PATH), ["quality_eval"])
    reports = _passing_reports_for_policy(policy)
    reports["quality_eval"]["metrics"]["recall_at_k"] = "unknown"

    report = evaluate_gate(policy, reports)

    self.assertFalse(report["passed"])
    self.assertIn(
        "metric_numeric:quality_eval.metrics.recall_at_k",
        {item["name"] for item in report["failed_checks"]},
    )
```

- [ ] **Step 2: Run threshold tests and verify RED**

Run:

```powershell
python -m pytest tests/test_release_gate.py -k "quality_thresholds or non_numeric_quality_metric" -q
```

Expected: boundary test passes, while the non-numeric test errors at `float("unknown")` instead of returning a failed check.

- [ ] **Step 3: Convert non-numeric metrics into explicit failed checks**

In `_evaluate_metric_thresholds()`, replace the unconditional conversion with:

```python
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
```

- [ ] **Step 4: Verify threshold tests are GREEN**

Run:

```powershell
python -m pytest tests/test_release_gate.py -k "quality_thresholds or non_numeric_quality_metric" -q
```

Expected: all selected tests pass.

- [ ] **Step 5: Write failing CLI environment tests**

Import `main` and `sys`, then add:

```python
import sys

from scripts.release_gate import main


def test_main_enables_quality_eval_from_environment(self) -> None:
    with (
        patch.dict(os.environ, {INCLUDE_QUALITY_EVAL_ENV: "true"}, clear=True),
        patch.object(sys, "argv", ["release_gate.py", "--json"]),
        patch(
            "scripts.release_gate.run_release_gate",
            return_value={"passed": True},
        ) as run,
    ):
        exit_code = main()

    self.assertEqual(exit_code, 0)
    self.assertTrue(run.call_args.kwargs["include_quality_eval"])


def test_main_cli_flag_enables_quality_eval(self) -> None:
    with (
        patch.dict(os.environ, {}, clear=True),
        patch.object(
            sys,
            "argv",
            ["release_gate.py", "--include-quality-eval", "--json"],
        ),
        patch(
            "scripts.release_gate.run_release_gate",
            return_value={"passed": True},
        ) as run,
    ):
        exit_code = main()

    self.assertEqual(exit_code, 0)
    self.assertTrue(run.call_args.kwargs["include_quality_eval"])


def test_main_rejects_invalid_quality_environment_value(self) -> None:
    with (
        patch.dict(os.environ, {INCLUDE_QUALITY_EVAL_ENV: "sometimes"}, clear=True),
        patch.object(sys, "argv", ["release_gate.py", "--json"]),
        patch("scripts.release_gate.run_release_gate") as run,
        self.assertRaises(SystemExit) as raised,
    ):
        main()

    self.assertEqual(raised.exception.code, 2)
    run.assert_not_called()
```

- [ ] **Step 6: Run CLI tests and verify RED**

Run:

```powershell
python -m pytest tests/test_release_gate.py -k "main_enables_quality or main_cli_flag or main_rejects_invalid" -q
```

Expected: the flag test errors because argparse does not recognize `--include-quality-eval`; the environment test observes `include_quality_eval` missing from the call.

- [ ] **Step 7: Wire the flag and environment variable at the CLI boundary**

Add the argument beside the existing release-gate arguments:

```python
    parser.add_argument(
        "--include-quality-eval",
        action="store_true",
        help="Include the policy-configured quality evaluation stage.",
    )
```

After `args = parser.parse_args()`, resolve the environment and update the call:

```python
    try:
        environment_requested = _environment_flag(INCLUDE_QUALITY_EVAL_ENV)
    except ValueError as exc:
        parser.error(str(exc))

    report = run_release_gate(
        policy_path=args.policy,
        output_dir=args.output_dir,
        include_quality_eval=args.include_quality_eval or environment_requested,
    )
```

- [ ] **Step 8: Add a failing Markdown report test**

Add:

```python
def test_gate_summary_lists_included_optional_stages(self) -> None:
    policy = activate_optional_stages(load_policy(DEFAULT_POLICY_PATH), ["quality_eval"])
    report = evaluate_gate(policy, _passing_reports_for_policy(policy))
    report["included_optional_stages"] = ["quality_eval"]

    with tempfile.TemporaryDirectory() as temp_dir:
        _, summary_path = write_report(report, temp_dir)
        summary = summary_path.read_text(encoding="utf-8")

    self.assertIn("optional_stages: quality_eval", summary)
    self.assertIn("| quality_eval | 6 | 6 | 1.0000 |", summary)
```

- [ ] **Step 9: Run the report test and verify RED**

Run:

```powershell
python -m pytest tests/test_release_gate.py::ReleaseGateTests::test_gate_summary_lists_included_optional_stages -q
```

Expected: FAIL because the summary does not render `optional_stages`.

- [ ] **Step 10: Render optional-stage state in Markdown**

In `write_report()`, resolve and render the stage list:

```python
    optional_stages = [str(item) for item in (report.get("included_optional_stages") or [])]
    optional_stage_label = ", ".join(optional_stages) if optional_stages else "none"
    lines = [
        "# Offline Evaluation Release Gate",
        "",
        f"- status: {status}",
        f"- generated_at: {report.get('generated_at', '')}",
        f"- optional_stages: {optional_stage_label}",
        f"- suites: {metrics.get('suite_count', 0)}",
```

Retain the remaining existing lines after `suites` unchanged.

- [ ] **Step 11: Verify all release-gate tests**

Run:

```powershell
python -m pytest tests/test_release_gate.py -q
```

Expected: all tests pass.

- [ ] **Step 12: Commit CLI, thresholds, and reporting**

```powershell
git add scripts/release_gate.py tests/test_release_gate.py
git commit -m "feat: expose quality release gate opt-in"
```

### Task 6: Document and Verify the Complete Workflow

**Files:**
- Modify: `docs/offline_evaluation_release_gate.md`
- Modify: `README.md:64-74`

- [ ] **Step 1: Update the release-gate guide**

Replace the opening description and run section with text that includes these exact commands and guarantees:

````markdown
The default release gate runs only deterministic offline smoke suites. It does not call
DashScope, Milvus, Neo4j, or any other external service.

## Run

Run the fast deterministic gate:

```powershell
python scripts/release_gate.py
```

Explicitly include the quality stage when its external dependencies and credentials are ready:

```powershell
python scripts/release_gate.py --include-quality-eval
```

The equivalent environment opt-in is:

```powershell
$env:RELEASE_GATE_INCLUDE_QUALITY_EVAL = "true"
python scripts/release_gate.py
```
````

Add a `Quality Stage Policy` subsection documenting `eval_quality`, `top_k=6`, answer generation,
six minimum cases, full suite pass rate, recall/faithfulness/citation minimums of `0.8`, P95 maximum
of `2000 ms`, and estimated-cost maximum of `$1.00`.

- [ ] **Step 2: Update the README command block**

Immediately after the existing release-gate command, add:

````markdown
The default command runs only the fast deterministic offline smoke gate. To include quality,
generation, latency, and cost thresholds in the same gate, explicitly run:

```powershell
python scripts/release_gate.py --include-quality-eval
```

Alternatively, set `RELEASE_GATE_INCLUDE_QUALITY_EVAL=true` before running the default command.
````

- [ ] **Step 3: Run focused evaluation and gate tests**

Run:

```powershell
python -m pytest tests/test_eval_queries.py tests/test_evaluation_metrics.py tests/test_release_gate.py -q
```

Expected: all tests pass.

- [ ] **Step 4: Run formatter and linter checks**

Run:

```powershell
python -m ruff format --check scripts/eval_queries.py scripts/release_gate.py tests/test_eval_queries.py tests/test_release_gate.py
python -m ruff check scripts/eval_queries.py scripts/release_gate.py tests/test_eval_queries.py tests/test_release_gate.py
```

Expected: both commands exit 0. If format check fails, run the same command without `--check`,
inspect the diff, and rerun both checks.

- [ ] **Step 5: Run the complete test suite**

Run:

```powershell
python -m pytest -q
```

Expected: all tests pass.

- [ ] **Step 6: Run repository hooks and inspect their edits**

Run:

```powershell
pre-commit run --all-files
git diff --check
git status --short
```

Expected: hooks pass, `git diff --check` exits 0, and status lists only files belonging to this
feature. Review any Ruff rewrite before proceeding.

- [ ] **Step 7: Verify the required default release gate**

Run:

```powershell
python scripts/release_gate.py
```

Expected: exit 0, five suites, 39/39 cases, and `optional_stages: none` in
`eval/reports/release_gate/summary.md`.

- [ ] **Step 8: Verify or explicitly defer the live quality run**

When model credentials, Milvus, and Neo4j are configured, run:

```powershell
python scripts/release_gate.py --include-quality-eval
```

Expected: the quality suite appears as the sixth suite and all configured thresholds pass. If the
external services are unavailable, do not weaken or bypass the policy; record this single skipped
integration check in the final handoff while retaining the unit-test evidence for opt-in wiring.

- [ ] **Step 9: Commit documentation and verified implementation state**

```powershell
git add README.md docs/offline_evaluation_release_gate.md scripts/eval_queries.py scripts/release_gate.py eval/release_gate.json tests/test_eval_queries.py tests/test_release_gate.py
git commit -m "docs: document opt-in quality release gate"
```

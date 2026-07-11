# Pressure CLI Exit And Default Baseline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make pressure failures observable through the process exit code and replace duplicated, overload-prone defaults with one cross-platform baseline configuration.

**Architecture:** `PressureScenario` remains the typed scenario contract and gains one immutable canonical default instance. Direct calls and argparse resolve from that instance, while `PressureReport` owns the status-to-exit-code mapping and `main(argv)` only orchestrates parsing, execution, output, and process termination.

**Tech Stack:** Python 3.11, `argparse`, frozen dataclasses, `unittest`, `pytest`, Ruff.

## Global Constraints

- Python must remain `>=3.11,<3.12`.
- Do not add production or development dependencies.
- `fail` exits 1; `pass` and `warn` exit 0.
- JSON and human output must use identical exit semantics.
- The canonical baseline is exactly 200 requests, 4 workers, 20 ms answer delay, 0 ms trace delay, trace queue size 32, 4 answer permits, and 0.25 second acquire timeout.
- Keep strict baseline thresholds; do not hide overload by relaxing rejection, completion, trace, retrieval, accounting, or latency checks.
- Keep dedicated saturation, SSE, model-budget, retrieval-degraded behavior and report JSON fields unchanged.
- Remove the old duplicated constants and `main() -> None` behavior instead of wrapping them in compatibility code.
- Ruff target is Python 3.11, 100-character lines, sorted imports, and double-quoted strings.

---

### Task 1: Canonical Typed Baseline Configuration

**Files:**
- Modify: `scripts/pressure_api_service.py:24-25,165-202,709-780,946-982,1076-1106`
- Test: `tests/test_pressure_api_service.py:1-15,230-275`

**Interfaces:**
- Consumes: existing frozen `PressureScenario` and `run_pressure_test(...)` behavior.
- Produces: `DEFAULT_PRESSURE_SCENARIO: PressureScenario`, `default_pressure_scenario(...) -> PressureScenario`, `run_pressure_test(...) -> PressureReport`, and `_parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace`.

- [ ] **Step 1: Write failing canonical-default tests**

Add `DEFAULT_PRESSURE_SCENARIO`, `_parse_args`, and `default_pressure_scenario` to the import list in `tests/test_pressure_api_service.py`, then add these methods to `PressureApiServiceTests`:

```python
    def test_default_scenario_has_one_cross_platform_baseline(self) -> None:
        scenario = default_pressure_scenario()

        self.assertEqual(scenario, DEFAULT_PRESSURE_SCENARIO)
        self.assertEqual(scenario.requests, 200)
        self.assertEqual(scenario.workers, scenario.max_concurrent_answers)
        self.assertEqual(scenario.workers, 4)
        self.assertEqual(scenario.answer_delay_ms, 20.0)
        self.assertEqual(scenario.trace_delay_ms, 0.0)
        self.assertEqual(scenario.trace_queue_size, 32)
        self.assertEqual(scenario.answer_acquire_timeout_seconds, 0.25)

    def test_cli_parser_reads_defaults_from_canonical_scenario(self) -> None:
        args = _parse_args([])

        self.assertEqual(args.scenario_name, DEFAULT_PRESSURE_SCENARIO.name)
        self.assertEqual(args.requests, DEFAULT_PRESSURE_SCENARIO.requests)
        self.assertEqual(args.workers, DEFAULT_PRESSURE_SCENARIO.workers)
        self.assertEqual(args.answer_delay_ms, DEFAULT_PRESSURE_SCENARIO.answer_delay_ms)
        self.assertEqual(args.trace_delay_ms, DEFAULT_PRESSURE_SCENARIO.trace_delay_ms)
        self.assertEqual(args.trace_queue_size, DEFAULT_PRESSURE_SCENARIO.trace_queue_size)
        self.assertEqual(
            args.max_concurrent_answers,
            DEFAULT_PRESSURE_SCENARIO.max_concurrent_answers,
        )
        self.assertEqual(
            args.answer_acquire_timeout_seconds,
            DEFAULT_PRESSURE_SCENARIO.answer_acquire_timeout_seconds,
        )

    def test_default_run_is_a_healthy_repeatable_baseline(self) -> None:
        payload = run_pressure_test().to_dict()

        self.assertEqual(payload["status"], "pass")
        self.assertEqual(payload["scenario"], DEFAULT_PRESSURE_SCENARIO.to_dict())
        self.assertEqual(payload["metrics"]["completed_requests"], 200)
        self.assertEqual(payload["metrics"]["rejected_requests"], 0)
        self.assertEqual(payload["metrics"]["trace"]["dropped_events"], 0)
        accounting = next(
            check for check in payload["checks"] if check["name"] == "request_accounting"
        )
        self.assertEqual(accounting["status"], "pass")
        self.assertIs(accounting["actual"], True)
```

- [ ] **Step 2: Run the new tests and verify RED**

Run:

```powershell
python -m pytest tests/test_pressure_api_service.py::PressureApiServiceTests::test_default_scenario_has_one_cross_platform_baseline tests/test_pressure_api_service.py::PressureApiServiceTests::test_cli_parser_reads_defaults_from_canonical_scenario tests/test_pressure_api_service.py::PressureApiServiceTests::test_default_run_is_a_healthy_repeatable_baseline -q
```

Expected: collection fails because `DEFAULT_PRESSURE_SCENARIO` does not exist, proving the tests require the new single source of truth.

- [ ] **Step 3: Replace duplicated defaults with the canonical scenario**

In `scripts/pressure_api_service.py`, import `Sequence` and remove `DEFAULT_MAX_CONCURRENT_ANSWERS` and `DEFAULT_SCENARIO_NAME`:

```python
from collections.abc import Sequence
```

Immediately after `PressureScenario`, define:

```python
DEFAULT_PRESSURE_SCENARIO = PressureScenario(
    name="api_concurrency_baseline",
    requests=200,
    workers=4,
    answer_delay_ms=20.0,
    trace_delay_ms=0.0,
    trace_queue_size=32,
    max_concurrent_answers=4,
    answer_acquire_timeout_seconds=0.25,
)
```

Replace `default_pressure_scenario` with optional overrides resolved from that instance:

```python
def default_pressure_scenario(
    *,
    scenario_name: str | None = None,
    requests: int | None = None,
    workers: int | None = None,
    answer_delay_ms: float | None = None,
    trace_delay_ms: float | None = None,
    trace_queue_size: int | None = None,
    max_concurrent_answers: int | None = None,
    answer_acquire_timeout_seconds: float | None = None,
    synthetic_model_latency_ms: float | None = None,
    synthetic_input_tokens_per_request: int | None = None,
    synthetic_output_tokens_per_request: int | None = None,
    input_cost_per_million_tokens: float | None = None,
    output_cost_per_million_tokens: float | None = None,
    retrieval_degraded_every: int | None = None,
    retrieval_degraded_source: str | None = None,
) -> PressureScenario:
    defaults = DEFAULT_PRESSURE_SCENARIO
    return PressureScenario(
        name=str(scenario_name or defaults.name),
        requests=max(1, int(defaults.requests if requests is None else requests)),
        workers=max(1, int(defaults.workers if workers is None else workers)),
        answer_delay_ms=max(
            0.0,
            float(defaults.answer_delay_ms if answer_delay_ms is None else answer_delay_ms),
        ),
        trace_delay_ms=max(
            0.0,
            float(defaults.trace_delay_ms if trace_delay_ms is None else trace_delay_ms),
        ),
        trace_queue_size=max(
            0,
            int(defaults.trace_queue_size if trace_queue_size is None else trace_queue_size),
        ),
        max_concurrent_answers=max(
            1,
            int(
                defaults.max_concurrent_answers
                if max_concurrent_answers is None
                else max_concurrent_answers
            ),
        ),
        answer_acquire_timeout_seconds=max(
            0.0,
            float(
                defaults.answer_acquire_timeout_seconds
                if answer_acquire_timeout_seconds is None
                else answer_acquire_timeout_seconds
            ),
        ),
        synthetic_model_latency_ms=max(
            0.0,
            float(
                defaults.synthetic_model_latency_ms
                if synthetic_model_latency_ms is None
                else synthetic_model_latency_ms
            ),
        ),
        synthetic_input_tokens_per_request=max(
            0,
            int(
                defaults.synthetic_input_tokens_per_request
                if synthetic_input_tokens_per_request is None
                else synthetic_input_tokens_per_request
            ),
        ),
        synthetic_output_tokens_per_request=max(
            0,
            int(
                defaults.synthetic_output_tokens_per_request
                if synthetic_output_tokens_per_request is None
                else synthetic_output_tokens_per_request
            ),
        ),
        input_cost_per_million_tokens=max(
            0.0,
            float(
                defaults.input_cost_per_million_tokens
                if input_cost_per_million_tokens is None
                else input_cost_per_million_tokens
            ),
        ),
        output_cost_per_million_tokens=max(
            0.0,
            float(
                defaults.output_cost_per_million_tokens
                if output_cost_per_million_tokens is None
                else output_cost_per_million_tokens
            ),
        ),
        retrieval_degraded_every=max(
            0,
            int(
                defaults.retrieval_degraded_every
                if retrieval_degraded_every is None
                else retrieval_degraded_every
            ),
        ),
        retrieval_degraded_source=str(
            retrieval_degraded_source or defaults.retrieval_degraded_source
        ),
    )
```

Change every `run_pressure_test` keyword default to `None` with the matching optional annotation and continue passing those values to `default_pressure_scenario`. Change `_parse_args` to accept `argv` and read every default from the canonical instance:

```python
def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    defaults = DEFAULT_PRESSURE_SCENARIO
    parser = argparse.ArgumentParser(
        description="Local pressure test for GraphRAGServingApiService concurrency and trace backpressure.",
    )
    parser.add_argument("--requests", type=int, default=defaults.requests)
    parser.add_argument("--workers", type=int, default=defaults.workers)
    parser.add_argument("--answer-delay-ms", type=float, default=defaults.answer_delay_ms)
    parser.add_argument("--trace-delay-ms", type=float, default=defaults.trace_delay_ms)
    parser.add_argument("--trace-queue-size", type=int, default=defaults.trace_queue_size)
    parser.add_argument("--scenario-name", default=defaults.name)
    parser.add_argument(
        "--max-concurrent-answers",
        type=int,
        default=defaults.max_concurrent_answers,
    )
    parser.add_argument(
        "--answer-acquire-timeout-seconds",
        type=float,
        default=defaults.answer_acquire_timeout_seconds,
    )
    parser.add_argument(
        "--synthetic-model-latency-ms",
        type=float,
        default=defaults.synthetic_model_latency_ms,
    )
    parser.add_argument(
        "--synthetic-input-tokens-per-request",
        type=int,
        default=defaults.synthetic_input_tokens_per_request,
    )
    parser.add_argument(
        "--synthetic-output-tokens-per-request",
        type=int,
        default=defaults.synthetic_output_tokens_per_request,
    )
    parser.add_argument(
        "--input-cost-per-million-tokens",
        type=float,
        default=defaults.input_cost_per_million_tokens,
    )
    parser.add_argument(
        "--output-cost-per-million-tokens",
        type=float,
        default=defaults.output_cost_per_million_tokens,
    )
    parser.add_argument(
        "--retrieval-degraded-every",
        type=int,
        default=defaults.retrieval_degraded_every,
    )
    parser.add_argument(
        "--retrieval-degraded-source",
        default=defaults.retrieval_degraded_source,
    )
    parser.add_argument("--json", action="store_true", help="Emit report as JSON.")
    return parser.parse_args(argv)
```

- [ ] **Step 4: Run canonical-default tests and verify GREEN**

Run the same three-test command from Step 2.

Expected: `3 passed`; the default report is `pass`, completes 200 requests, rejects none, drops no traces, and balances request accounting.

- [ ] **Step 5: Run the full focused pressure test module**

Run:

```powershell
python -m pytest tests/test_pressure_api_service.py -q
```

Expected: all pressure tests pass with no warnings or errors.

- [ ] **Step 6: Commit the canonical baseline refactor**

```powershell
git add scripts/pressure_api_service.py tests/test_pressure_api_service.py
git commit -m "refactor: centralize pressure baseline defaults"
```

---

### Task 2: Report-Owned Exit Contract And Real CLI Termination

**Files:**
- Modify: `scripts/pressure_api_service.py:428-451,1076-1164`
- Test: `tests/test_pressure_api_service.py:1-15,55-220,370-390`

**Interfaces:**
- Consumes: `PressureReport.status`, canonical `_parse_args(argv)`, and `run_pressure_test(...)` from Task 1.
- Produces: `PressureReport.exit_code: int`, `main(argv: Sequence[str] | None = None) -> int`, and a module entry point that raises `SystemExit(main())`.

- [ ] **Step 1: Write failing report and CLI exit tests**

Add `io`, `json`, `subprocess`, `sys`, `redirect_stdout`, and `Path` imports. Add `PressureCheck`, `PressureReport`, `main`, and `default_pressure_thresholds` to the script imports. Add these tests:

```python
    def test_report_exit_code_is_nonzero_only_for_fail(self) -> None:
        scenario = default_pressure_scenario(requests=1, workers=1)
        metrics = _metrics(requests=1, completed_requests=1)
        thresholds = default_pressure_thresholds(scenario)

        for status, expected in (("pass", 0), ("warn", 0), ("fail", 1)):
            with self.subTest(status=status):
                report = PressureReport(
                    scenario=scenario,
                    metrics=metrics,
                    thresholds=thresholds,
                    checks=[
                        PressureCheck(
                            name="exit_contract",
                            status=status,
                            actual=True,
                            operator="is",
                            limit=True,
                            message="Exercise the process exit contract.",
                        )
                    ],
                )
                self.assertEqual(report.status, status)
                self.assertEqual(report.exit_code, expected)

    def test_main_returns_one_and_preserves_json_for_failed_report(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            exit_code = main(
                [
                    "--json",
                    "--scenario-name",
                    "model_call_budget",
                    "--requests",
                    "1",
                    "--workers",
                    "1",
                    "--answer-delay-ms",
                    "0",
                    "--trace-delay-ms",
                    "0",
                    "--synthetic-model-latency-ms",
                    "1001",
                ]
            )

        self.assertEqual(exit_code, 1)
        self.assertEqual(json.loads(output.getvalue())["status"], "fail")

    def test_main_returns_zero_after_human_pass_report(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            exit_code = main(
                [
                    "--scenario-name",
                    "model_call_budget",
                    "--requests",
                    "1",
                    "--workers",
                    "1",
                    "--answer-delay-ms",
                    "0",
                    "--trace-delay-ms",
                    "0",
                ]
            )

        self.assertEqual(exit_code, 0)
        self.assertIn("Status: pass", output.getvalue())

    def test_script_process_exits_one_and_emits_failed_json(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        completed = subprocess.run(
            [
                sys.executable,
                str(project_root / "scripts" / "pressure_api_service.py"),
                "--json",
                "--scenario-name",
                "model_call_budget",
                "--requests",
                "1",
                "--workers",
                "1",
                "--answer-delay-ms",
                "0",
                "--trace-delay-ms",
                "0",
                "--synthetic-model-latency-ms",
                "1001",
            ],
            cwd=project_root,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(completed.returncode, 1, completed.stderr)
        self.assertEqual(json.loads(completed.stdout)["status"], "fail")
```

- [ ] **Step 2: Run exit-contract tests and verify RED**

Run:

```powershell
python -m pytest tests/test_pressure_api_service.py::PressureApiServiceTests::test_report_exit_code_is_nonzero_only_for_fail tests/test_pressure_api_service.py::PressureApiServiceTests::test_main_returns_one_and_preserves_json_for_failed_report tests/test_pressure_api_service.py::PressureApiServiceTests::test_main_returns_zero_after_human_pass_report tests/test_pressure_api_service.py::PressureApiServiceTests::test_script_process_exits_one_and_emits_failed_json -q
```

Expected: failures show that `PressureReport.exit_code` is absent, `main` does not accept argv or return a code, and the subprocess returns 0.

- [ ] **Step 3: Make the report own exit classification**

Add this property immediately after `PressureReport.status`:

```python
    @property
    def exit_code(self) -> int:
        return 1 if self.status == "fail" else 0
```

Replace `main` and the module entry point with:

```python
def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    report = run_pressure_test(
        scenario_name=args.scenario_name,
        requests=args.requests,
        workers=args.workers,
        answer_delay_ms=args.answer_delay_ms,
        trace_delay_ms=args.trace_delay_ms,
        trace_queue_size=args.trace_queue_size,
        max_concurrent_answers=args.max_concurrent_answers,
        answer_acquire_timeout_seconds=args.answer_acquire_timeout_seconds,
        synthetic_model_latency_ms=args.synthetic_model_latency_ms,
        synthetic_input_tokens_per_request=args.synthetic_input_tokens_per_request,
        synthetic_output_tokens_per_request=args.synthetic_output_tokens_per_request,
        input_cost_per_million_tokens=args.input_cost_per_million_tokens,
        output_cost_per_million_tokens=args.output_cost_per_million_tokens,
        retrieval_degraded_every=args.retrieval_degraded_every,
        retrieval_degraded_source=args.retrieval_degraded_source,
    )
    payload = report.to_dict()
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        _print_human_report(payload)
    return report.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run exit-contract tests and verify GREEN**

Run the same four-test command from Step 2.

Expected: `4 passed`; both output modes preserve their report and the real failing subprocess exits 1.

- [ ] **Step 5: Run all focused pressure tests**

Run:

```powershell
python -m pytest tests/test_pressure_api_service.py -q
```

Expected: all tests pass without warnings or errors.

- [ ] **Step 6: Commit the exit contract**

```powershell
git add scripts/pressure_api_service.py tests/test_pressure_api_service.py
git commit -m "fix: return nonzero for failed pressure reports"
```

---

### Task 3: Operator Contract And Release-Sensitive Verification

**Files:**
- Modify: `docs/api_capacity_and_pressure_thresholds.md:1-12,68-82,117-130`
- Verify: `scripts/pressure_api_service.py`
- Verify: `tests/test_pressure_api_service.py`

**Interfaces:**
- Consumes: canonical baseline and exit semantics from Tasks 1 and 2.
- Produces: documented operator expectations and final verification evidence.

- [ ] **Step 1: Document the new baseline and process contract**

After the introductory host-dependent note in `docs/api_capacity_and_pressure_thresholds.md`, add:

```markdown
The default baseline is intentionally scheduler-neutral: its four workers match
the four answer permits and its in-memory trace sink adds no synthetic delay.
Use the saturation scenario or explicit trace-delay flags when testing overload
and trace backpressure.
```

After the report status derivation list, add:

```markdown
CLI exit codes follow the same report classification:

- `0` for `pass` and `warn`, because both are completed observations;
- `1` for `fail`, after the full JSON or human-readable report is emitted.

This applies to `python scripts/pressure_api_service.py`, the
`graph-rag-pressure` console entry point, and both output formats.
```

- [ ] **Step 2: Run the focused tests**

Run:

```powershell
python -m pytest tests/test_pressure_api_service.py -q
```

Expected: all focused tests pass.

- [ ] **Step 3: Run Ruff on changed Python files**

Run:

```powershell
python -m ruff check scripts/pressure_api_service.py tests/test_pressure_api_service.py
```

Expected: exit 0 with no diagnostics. If Ruff changes are required, apply only mechanical formatting/import fixes and rerun both Ruff and the focused tests.

- [ ] **Step 4: Verify the default CLI repeatedly**

Run this command three separate times:

```powershell
python scripts/pressure_api_service.py --json
```

Expected each time: process exit 0, top-level status `pass`, 200 completed requests, zero rejected requests, zero trace drops, and a passing request-accounting check.

- [ ] **Step 5: Verify a deterministic failing subprocess**

Run:

```powershell
python scripts/pressure_api_service.py --json --scenario-name model_call_budget --requests 1 --workers 1 --answer-delay-ms 0 --trace-delay-ms 0 --synthetic-model-latency-ms 1001
```

Expected: the full JSON report has top-level status `fail` and the process exits 1.

- [ ] **Step 6: Run the release gate**

Run:

```powershell
python scripts/release_gate.py
```

Expected: exit 0 and a passing release-gate report. If an external or environment-specific prerequisite is unavailable, record the exact failed check and keep the focused tests and CLI evidence separate.

- [ ] **Step 7: Check the final diff**

Run:

```powershell
git diff --check
git status --short
git diff -- scripts/pressure_api_service.py tests/test_pressure_api_service.py docs/api_capacity_and_pressure_thresholds.md
```

Expected: no whitespace errors; only the pressure CLI, its focused tests, and its operator documentation are modified.

- [ ] **Step 8: Commit documentation and final verification-ready state**

```powershell
git add docs/api_capacity_and_pressure_thresholds.md scripts/pressure_api_service.py tests/test_pressure_api_service.py
git commit -m "docs: define pressure CLI exit contract"
```

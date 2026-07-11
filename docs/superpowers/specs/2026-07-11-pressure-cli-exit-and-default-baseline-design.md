# Pressure CLI Exit And Default Baseline Design

## Context

The pressure CLI already classifies reports as `pass`, `warn`, or `fail`, but
the process always exits successfully because `main()` discards the report
status and the module entry point does not raise `SystemExit`. The default
`api_concurrency_baseline` is also internally contradictory: it starts 16
workers against 4 answer permits while requiring zero admission rejections,
and it adds a synthetic 5 ms trace sink delay while requiring zero trace drops.

On Windows, the current defaults reproduced `fail` three times with 164 of 200
requests completed and 36 rejected. Running the same workload with four workers
and no synthetic trace delay reproduced `pass` three times with 200 of 200
requests completed, no rejections, and no trace drops.

## Goals

- Return a non-zero process exit code exactly when the pressure report status is
  `fail`.
- Keep `pass` and `warn` usable as successful CLI observations with exit code 0.
- Make the default baseline measure healthy ordinary load instead of accidental
  saturation or trace backpressure.
- Keep all defaults in one typed source shared by direct Python calls and CLI
  argument parsing.
- Preserve the structured report schema while removing duplicated default
  declarations and implicit exit behavior.

## Non-Goals

- Do not relax failure thresholds to make an overloaded default appear healthy.
- Do not derive defaults from CPU count or operating-system identity.
- Do not change dedicated saturation, SSE, model-budget, or retrieval-degraded
  scenario semantics.
- Do not add a compatibility wrapper around the old `main() -> None` behavior.

## Design

### Canonical default scenario

Define one immutable `PressureScenario` instance as the canonical default. It
uses 200 requests, 4 workers, 20 ms answer delay, 0 ms trace delay, a trace
queue size of 32, 4 answer permits, and a 0.25 second acquire timeout. The
remaining synthetic model and retrieval fields stay at zero/default values.

`default_pressure_scenario(...)` accepts optional overrides and resolves every
omitted value from this instance. `run_pressure_test(...)` delegates omitted
values to that resolver. `_parse_args(...)` reads its argparse defaults from the
same instance. This removes the three independent declarations that allowed the
CLI and Python entry points to drift.

The baseline thresholds remain strict: zero rejection, all requests completed,
zero trace drops and failures, zero retrieval degradation, balanced accounting,
and p95 latency at or below 250 ms. Dedicated scenarios remain the place for
intentional overload and slow trace behavior.

### Exit contract

`PressureReport` exposes an `exit_code` property. It returns 1 for `fail` and 0
for `pass` or `warn`. This keeps status aggregation and process classification
in the report model rather than duplicating string comparisons in output paths.

`main(argv=None) -> int` parses the supplied argument sequence, runs the
scenario, emits either JSON or the human report, and returns
`report.exit_code`. Both output modes follow the same contract. The module entry
point uses `raise SystemExit(main())`, so direct script execution and the
`graph-rag-pressure` console entry point observe the returned code naturally.

No legacy `main() -> None` adapter or status-specific printing branch is kept.

### Documentation

The operator guide will state that `fail` exits 1 while `pass` and `warn` exit
0. Its baseline section will explain that default worker count matches answer
permits and that the default trace sink has no synthetic delay; overload and
trace-backpressure experiments require explicit scenario arguments.

## Testing

Follow test-first development:

1. Add report tests proving `fail -> 1` and `pass`/`warn -> 0`.
2. Add parser tests proving the canonical four-worker, zero-trace-delay defaults.
3. Add a default-run test requiring `pass`, complete accounting, zero rejection,
   and zero trace drops.
4. Add CLI tests for both JSON and human output return values.
5. Add a subprocess test proving an intentionally failing deterministic model
   budget scenario exits 1 and still emits a valid JSON report with `fail`.

Run the focused pressure tests first, then Ruff/pre-commit-equivalent checks for
changed files, the documented default CLI command, and the release gate because
this changes a release-sensitive command-line contract.

## Acceptance Criteria

- A report with status `fail` causes direct script and console-entry execution
  to exit 1 after printing the full report.
- Reports with status `pass` or `warn` exit 0.
- JSON and human-readable modes have identical exit semantics.
- The default baseline uses one canonical typed configuration and passes
  repeatedly without admission rejection or trace drops on supported platforms.
- Existing dedicated pressure scenarios and report JSON fields remain intact.
- Focused tests and release-sensitive validation pass.

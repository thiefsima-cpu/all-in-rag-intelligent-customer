# Opt-in Quality Evaluation Release Gate Design

## Context

`scripts/release_gate.py` currently runs five deterministic offline smoke suites. The default
policy in `eval/release_gate.json` requires 39 cases, full pass rates, route-category coverage,
and real-route contract metrics. This path is fast, deterministic, and independent of external
services.

`scripts/eval_queries.py` already provides a broader quality evaluation over the curated corpus.
With generation enabled it reports retrieval, grounding, latency, token, and cost metrics, but it
is not part of the release gate. Quality evaluation may initialize model, Milvus, and Neo4j
dependencies, so it must remain an explicit opt-in rather than changing the default gate.

## Goals

- Preserve the existing default release-gate behavior and its five-suite, 39-case contract.
- Allow quality evaluation to join the gate with one CLI flag or one environment variable.
- Keep the quality runner settings and thresholds in the default policy.
- Run the quality profile with answer generation enabled so grounding and cost metrics are real.
- Include the optional stage and its checks in the existing JSON and Markdown reports.

## Non-goals

- Do not make quality evaluation deterministic or suitable for the default smoke path.
- Do not add a general-purpose workflow engine or arbitrary plugin mechanism.
- Do not change the curated corpus, evaluation formulas, or runtime profiles.
- Do not add dependencies or change public package APIs.

## Selected Approach

Use a policy-native optional stage. The release gate will recognize the single
`quality_eval` stage, activate it only when requested, and translate its policy block into the
same suite and metric checks used by required smoke suites.

Two alternatives were rejected:

1. Hard-code quality settings in `release_gate.py`. This is smaller initially but conflicts with
   the repository's configuration-driven behavior and separates thresholds from runner settings.
2. Spawn `scripts/eval_queries.py` as a subprocess and parse its output. This isolates the
   process, but it makes error handling and structured report transfer more brittle.

## User Interface

The default command is unchanged:

```powershell
python scripts/release_gate.py
```

Quality evaluation can be included explicitly:

```powershell
python scripts/release_gate.py --include-quality-eval
```

or through the process environment:

```powershell
$env:RELEASE_GATE_INCLUDE_QUALITY_EVAL = "true"
python scripts/release_gate.py
```

The environment parser accepts `1`, `true`, `yes`, and `on` as true and `0`, `false`, `no`, and
`off` as false, case-insensitively. An unrecognized value is an input error and no suites run.
The CLI flag and a true environment value are combined with OR semantics.

The programmatic `run_release_gate()` entry point receives an explicit
`include_quality_eval: bool = False` argument. Environment handling remains at the CLI boundary,
so library callers are deterministic.

## Policy Shape

The schema remains version 1 because the new key is optional and existing policies continue to
work for the default gate. The default policy adds this block:

```json
{
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
}
```

When selected, the gate creates an active policy view by appending the stage suite to
`required_suites`, adding its case and pass-rate requirements, and merging its metric thresholds.
The loaded policy object is not mutated. Duplicate suite names or metric keys are configuration
errors instead of silently overriding required-gate behavior.

Requesting quality evaluation with a custom policy that does not define
`optional_stages.quality_eval` is a configuration error. Running that same custom policy without
the opt-in remains backward compatible.

## Components and Data Flow

### Quality report function

`scripts/eval_queries.py` will extract the current initialize/evaluate/close sequence into a
function that returns the existing structured evaluation report. The current CLI-oriented
`run_eval()` function will call it, then retain responsibility for writing and printing results.
This keeps one quality-evaluation implementation and avoids capturing stdout.

### Release-gate adapter

`scripts/release_gate.py` will lazily import the quality report function only after the optional
stage is selected. The adapter passes the policy's profile, top-k, and generation settings and
normalizes the result into the existing suite contract:

- top-level `case_count` comes from quality metrics;
- `passed_count` is derived from the quality results;
- the complete quality metrics remain under `metrics`;
- results and failures remain available for diagnostics.

The normalized report then flows through `run_suites()` and `evaluate_gate()` exactly like other
suites. The default path neither imports the quality evaluator nor initializes its runtime.

### Reports

Release-gate reports add `included_optional_stages`, which is an empty list for the default run
and `['quality_eval']` for an opted-in run. When active, `quality_eval` appears in
`suite_metrics`, `suite_reports`, total case counts, checks, and the Markdown suite table.

## Error Handling

- Invalid environment values fail before suite execution with the variable name in the message.
- Missing or malformed selected-stage policy fails before suite execution with the policy path.
- Unknown suites and runner exceptions continue to become `suite_error` reports and fail the
  gate through normal availability, case, and pass-rate checks.
- Missing or non-numeric selected metrics fail their threshold checks rather than being ignored.
- Quality resource or provider failures are contained in the optional suite report; they do not
  change behavior when quality evaluation is not selected.

## Testing

Focused tests will prove:

- the default policy still selects exactly the five smoke suites and 39 cases;
- the CLI flag and each true environment spelling enable quality evaluation;
- false environment spellings preserve the smoke-only path and invalid values fail clearly;
- selecting the stage merges its suite constraints and metric thresholds without mutating policy;
- a synthetic quality report passes at the configured boundaries and fails below or above each
  threshold;
- the release-gate adapter normalizes the structured quality report;
- quality evaluator failures become a failed optional suite;
- JSON and Markdown reports identify whether the optional stage ran;
- `run_eval()` retains its current output and exit-code contract after report extraction.

Implementation will follow test-driven development: add focused failing tests, observe the
expected failures, implement the minimum behavior, and then run the broader release-gate and
evaluation test files. Before completion, run the default release gate to confirm the fast smoke
contract remains intact. The live opt-in quality run may require configured external services and
credentials; if unavailable, report that verification separately rather than weakening policy.

## Documentation

Update `docs/offline_evaluation_release_gate.md` and the README command section to distinguish the
default deterministic smoke gate from the explicitly enabled quality gate, list both opt-in
mechanisms, and document the default quality profile and thresholds.

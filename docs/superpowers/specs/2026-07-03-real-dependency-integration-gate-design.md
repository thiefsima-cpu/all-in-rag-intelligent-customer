# Real-Dependency Integration Gate Design

## Context

The existing release gate is intentionally deterministic and offline. It validates route,
retrieval, generation-plan, prompt, and curated quality behavior without requiring a model
provider, Milvus, or Neo4j. That remains the correct default release check, but it cannot prove
that a deployed dependency stack works end to end.

The repository therefore needs a second, explicitly invoked gate for a prepared environment. The
new gate must verify real Neo4j, Milvus, serving API, and model-provider behavior while keeping
online cost and infrastructure instability out of the offline gate.

## Goals

- Add an opt-in real-dependency integration gate with its own command, policy, reports, and docs.
- Prove that Neo4j, Milvus, the serving API, and the configured model provider participate in real
  end-to-end answer requests.
- Produce stable, typed, actionable failure classifications without parsing exception strings.
- Reuse a small generic gate kernel for policy checks, result aggregation, and reporting.
- Remove obsolete optional-quality compatibility behavior from the offline gate rather than
  carrying parallel legacy paths.
- Keep credentials and sensitive payloads out of policy files and generated reports.

## Non-goals

- The gate does not start, stop, rebuild, or destroy Docker services.
- The gate does not provision graph or vector data. A build/bootstrap workflow prepares the target
  environment before the gate runs.
- The gate does not replace offline evaluation or assert exact generated prose.
- The gate does not run as part of the default pytest or offline release-gate commands.
- The gate does not introduce a general plugin framework for arbitrary external systems.

## Chosen Architecture

Use two independent gate applications over a shared gate kernel:

- `graph-rag-release-gate` remains the deterministic offline application.
- `graph-rag-integration-gate` connects to an already-running environment and performs real
  dependency probes plus live answer cases.
- A focused `scripts/gates/` package owns shared typed results, metric-threshold evaluation, and
  report primitives. Domain-specific policy parsing and execution stay in the owning offline or
  integration module.

This preserves the different operational contracts. An offline failure is a deterministic code or
quality regression. An integration failure may instead mean an unavailable dependency, invalid
deployment contract, live quality regression, or budget regression.

The gate kernel is not a compatibility facade around the current monolithic
`scripts/release_policy.py`. The implementation will split the reusable behavior, update current
callers, and delete obsolete branches and exports.

## Components

### Shared gate kernel

The shared kernel provides four narrow concepts:

- `GateCheckResult`: a typed result containing `name`, `passed`, `status`, `failure_type`, `code`,
  `expected`, `actual`, and `duration_ms`.
- Threshold evaluation for finite numeric minimum and maximum rules.
- Aggregate gate status and failure-type counts.
- JSON and Markdown-safe report serialization helpers.

It does not know about route categories, quality dimensions, Neo4j, Milvus, HTTP, or model
providers. Those remain application-specific.

### Integration policy and configuration

`eval/integration_gate.json` contains only non-secret behavior:

- schema version;
- dependency minimums;
- request and probe timeouts;
- live cases and their required route/evidence contracts;
- fallback, degradation, latency, token, and cost thresholds.

Runtime endpoints and credentials come from environment variables:

- `INTEGRATION_GATE_API_URL` and optional `INTEGRATION_GATE_API_TOKEN`;
- the existing `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD`, and `NEO4J_DATABASE` variables;
- the existing `MILVUS_HOST`, `MILVUS_PORT`, and `MILVUS_COLLECTION_NAME` variables.

The serving application owns provider configuration through its existing provider-key variables.
The gate does not need or accept the raw model API key because model use is proven through the
serving API. Configuration validation happens before any network call. Missing required values,
malformed cases, duplicate IDs, invalid thresholds, and non-positive timeouts are configuration
errors.

### Dependency probes

Each probe is an adapter behind a small protocol so unit tests can use in-memory fakes without
production test branches.

- Neo4j verifies driver connectivity, opens the configured database, runs a read-only count query,
  and requires the configured minimum number of `Recipe` nodes.
- Milvus resolves the configured collection or alias, verifies it exists and is loadable, and
  requires the configured minimum entity count.
- Serving API calls `/v1/health/ready`, then `/v1/diagnostics`, and requires ready artifacts,
  initialized retrieval engines, and a ready system.

Probes return typed results with stable error codes. They do not expose raw driver or HTTP
exceptions. If a required probe fails, live cases are recorded as blocked and no model calls are
made.

### Live case runner

The runner calls `POST /v1/debug/answers` because the public answer contract intentionally hides
the route and trace detail needed to prove dependency participation. It sends an optional bearer
token and a generated correlation ID.

The initial policy contains three curated cases:

- a semantic recipe lookup that requires vector evidence;
- a relationship query that requires graph evidence;
- a constrained or multi-hop query that requires the combined route and both dependency paths.

Each case declares its allowed strategies, required evidence sources, minimum evidence count,
whether generation is required, and a per-case timeout. Assertions target stable structure and
semantics, not exact prose. A generation-required case passes the provider-participation check only
when the answer reports positive model-token usage and no generation fallback. A retrieval path is
counted only when the debug route/trace and evidence contract both show that source and no matching
source degradation is present.

The runner attempts all live cases after successful probes so one invocation produces a useful
diagnostic set. It uses no retries for semantic or contract failures. A single bounded retry may be
used only for explicitly classified transient HTTP transport failures, and both attempts are
recorded in the result.

### Integration evaluator and reporter

The evaluator requires:

- all dependency probes to pass;
- every live case to satisfy its contract;
- at least one proven Milvus path and one proven Neo4j path;
- positive model-token usage for every generation-required case;
- zero fallback and zero retrieval degradation;
- aggregate P95 latency and estimated cost within policy limits.

Reports are written independently to:

- `eval/reports/integration_gate/report.json`;
- `eval/reports/integration_gate/summary.md`.

The JSON report contains check results, aggregate metrics, policy path, timestamps, and safe target
identity. The Markdown report prioritizes failure types and stable codes. Neither report includes
API keys, passwords, authorization headers, credential-bearing URLs, raw provider responses, raw
exceptions, complete prompts, or complete user queries. Case IDs and sanitized endpoint hostnames
are sufficient for diagnosis.

## Execution Flow

1. Load and validate the integration policy.
2. Load and validate runtime environment configuration.
3. Run Neo4j, Milvus, and serving readiness probes.
4. If a required probe fails, mark live cases blocked and write the report without model calls.
5. Otherwise run all live cases through `/v1/debug/answers`.
6. Normalize response data into typed observations.
7. Evaluate per-case contracts and aggregate thresholds.
8. Write JSON and Markdown reports.
9. Exit with the status defined below.

The gate never mutates graph data, vector collections, artifacts, or application lifecycle state.

## Failure Model and Exit Codes

The stable failure types are:

- `dependency-unavailable`: connection, authentication, database, collection, or API readiness
  failure;
- `contract-regression`: invalid API response shape, missing trace/evidence fields, or an unexpected
  route contract;
- `quality-regression`: fallback, degraded retrieval, missing required evidence, or an otherwise
  unsuccessful live case;
- `budget-regression`: latency, token, or estimated-cost threshold failure;
- `gate-error`: invalid policy/configuration or an internal gate defect.

Failure classification is explicit at the boundary that understands the failure. It is never
derived by searching exception messages for words such as `neo4j`, `timeout`, or `connection`.

CLI exit codes are:

- `0`: the gate evaluated and passed;
- `1`: the environment was evaluated and one or more gate checks failed;
- `2`: configuration was invalid or the gate itself could not produce a valid evaluation.

Blocked live cases are reported with `status: blocked`. They do not become synthetic quality
failures; the dependency failure remains the cause of the failed gate.

## Offline Gate Cleanup

The offline quality evaluation is already required by the default release policy. The following
legacy compatibility surfaces will be deleted:

- `--include-quality-eval`;
- `RELEASE_GATE_INCLUDE_QUALITY_EVAL`;
- `optional_stages` activation and merging;
- fallback lookup of a required quality runner through an optional-stage definition;
- optional-stage report fields, summary labels, exports, and tests.

The required `quality_eval` suite remains configured directly under `suite_runners`. No deprecated
argument, environment alias, dual policy schema, warning-only shim, or compatibility re-export is
retained.

## Testing Strategy

### Unit tests

Unit tests inject fake Neo4j, Milvus, and HTTP adapters and cover:

- strict policy and environment configuration validation;
- successful probes and every stable probe failure code;
- blocked live cases after failed prerequisites;
- vector, graph, and combined participation assertions;
- provider-token and no-fallback requirements;
- threshold boundaries and non-finite metric rejection;
- failure aggregation, redaction, reports, and exit-code selection.

Tests assert observable contracts rather than calls internal to third-party SDKs.

### CLI and repository contract tests

Tests cover the new console entry point, JSON output, independent default paths, and invalid
configuration behavior. Existing release-gate tests are rewritten around the required-only policy.
Entrypoint and public-surface manifest tests are updated where applicable. Searches and tests assert
that removed compatibility names no longer exist in production code, current tests, or current
operator documentation.

### Real execution

The real integration gate is the opt-in live test. It is not added to default pytest, pre-commit,
`scripts/local_gate.py`, or the offline release gate. CI or an operator first prepares a target
environment and then runs:

```powershell
graph-rag-integration-gate
```

Local implementation verification must run focused tests, the full pytest suite, Ruff or
pre-commit, and the offline release gate. A live integration result may be claimed only when the
required services and provider credentials are available and the command was actually run.

## Documentation and Operations

Add a dedicated real-dependency gate document describing prerequisites, environment variables,
command usage, policy ownership, report interpretation, model cost, and CI scheduling. Update the
README and offline gate document to show the two-layer quality model and explicitly state that the
offline command remains dependency-free.

The recommended operational cadence is:

- offline release gate on every release candidate and normal local gate;
- real-dependency gate on a prepared pre-release environment and on a scheduled CI job;
- no automatic teardown by the gate, because the target may be shared or remotely managed.

## Acceptance Criteria

- The offline release gate remains deterministic and requires no external services.
- The obsolete optional-quality compatibility surfaces are absent.
- The integration gate is a separate installed console command with independent policy and reports.
- A failed Neo4j, Milvus, or API prerequisite prevents model calls and is reported as
  `dependency-unavailable`.
- Successful live execution proves at least one Milvus path, one Neo4j path, and real model usage.
- Live assertions do not depend on exact model wording.
- Reports and console output contain no secrets or raw sensitive payloads.
- Unit, CLI, full-suite, formatting/lint, and offline release-gate checks pass.
- Live-gate verification is reported honestly as run or not run according to environment
  availability.

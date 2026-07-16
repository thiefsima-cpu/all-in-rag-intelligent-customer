# Risk-Module Coverage Policy Design

**Date:** 2026-07-15  
**Status:** Approved for implementation planning

## Context

The repository currently enforces 75% combined coverage through coverage.py and 70% branch
coverage across the complete `rag_modules` package through
`scripts/check_branch_coverage.py`. The current full-suite report passes both gates, with 86.72%
combined coverage and 70.43% package branch coverage. The package branch margin is only 0.43
percentage points, and package aggregation lets well-tested modules hide weak critical paths.

The current report shows the following risk files below an acceptable level:

| File | Combined coverage | Branch coverage |
| --- | ---: | ---: |
| `rag_modules/retrieval/fusion.py` | 15.69% | 0.00% |
| `rag_modules/retrieval/adapters/constraint_retriever.py` | 34.48% | 0.00% |
| `rag_modules/retrieval/keyword_service.py` | 26.00% | 0.00% |
| `rag_modules/retrieval/adapters/bm25_retriever.py` | 58.88% | 40.91% |
| `rag_modules/retrieval/hybrid_driver_service.py` | 33.33% | 0.00% |
| `rag_modules/infra/milvus/schema.py` | 22.45% | 0.00% |
| `rag_modules/infra/milvus/client.py` | 28.41% | 16.67% |
| `rag_modules/app/composition/build_runtime_executor.py` | 30.43% | 0.00% |
| `rag_modules/runtime/build_jobs/locks.py` | 69.79% | 45.45% |

## Goals

- Replace the package-only branch checker with one coverage-policy engine.
- Retain the existing global combined and package branch gates.
- Enforce both combined and branch coverage on every configured risk file independently.
- Raise all nine initial risk files to at least 85% combined coverage and 80% branch coverage.
- Exercise meaningful failure, empty-result, degradation, concurrency, and resource-cleanup paths.
- Produce deterministic diagnostics that identify every failing rule in one run.
- Use the same policy and path semantics on Windows development machines and Linux CI workers.

## Non-Goals

- Do not raise the repository-wide 75% combined threshold or 70% package branch threshold in
  this change.
- Do not connect to a live Milvus or Neo4j service, start Docker, or add integration-only tests.
- Do not add runtime or development dependencies.
- Do not preserve the old script name, old configuration key, or old local-gate step name.
- Do not add exceptions that let a configured risk file omit branch data or inherit a weaker
  threshold.

## Chosen Architecture

Create a `scripts/coverage_policy/` package with five focused responsibilities:

- `models.py` defines immutable policy, coverage-count, rule-result, and evaluation-report types.
- `policy.py` parses and strictly validates the coverage policy in `pyproject.toml`.
- `snapshot.py` parses coverage.py JSON, normalizes paths, validates raw counts, and calculates
  package and file metrics.
- `evaluator.py` evaluates all rules without threshold fail-fast and returns ordered results.
- `cli.py` owns argument parsing, output formatting, and exit-code mapping.

`scripts/check_coverage_policy.py` is a thin executable entry that delegates to `cli.main`. The
existing `scripts/check_branch_coverage.py` and its old tests are removed rather than wrapped.

The policy engine does not replace coverage.py's global `fail_under = 75`. It adds two explicit
layers after the full suite writes `coverage.json`:

1. package branch coverage for `rag_modules` at 70%;
2. combined and branch coverage for each configured risk file at 85% and 80% respectively.

## Configuration Contract

Replace the scalar `rag_modules_branch_fail_under` key with a structured package rule and explicit
risk-module entries:

```toml
[tool.graph_rag.coverage.package]
path = "rag_modules"
branch_fail_under = 70

[[tool.graph_rag.coverage.risk_modules]]
path = "rag_modules/retrieval/fusion.py"
combined_fail_under = 85
branch_fail_under = 80

[[tool.graph_rag.coverage.risk_modules]]
path = "rag_modules/retrieval/adapters/constraint_retriever.py"
combined_fail_under = 85
branch_fail_under = 80

[[tool.graph_rag.coverage.risk_modules]]
path = "rag_modules/retrieval/keyword_service.py"
combined_fail_under = 85
branch_fail_under = 80

[[tool.graph_rag.coverage.risk_modules]]
path = "rag_modules/retrieval/adapters/bm25_retriever.py"
combined_fail_under = 85
branch_fail_under = 80

[[tool.graph_rag.coverage.risk_modules]]
path = "rag_modules/retrieval/hybrid_driver_service.py"
combined_fail_under = 85
branch_fail_under = 80

[[tool.graph_rag.coverage.risk_modules]]
path = "rag_modules/infra/milvus/schema.py"
combined_fail_under = 85
branch_fail_under = 80

[[tool.graph_rag.coverage.risk_modules]]
path = "rag_modules/infra/milvus/client.py"
combined_fail_under = 85
branch_fail_under = 80

[[tool.graph_rag.coverage.risk_modules]]
path = "rag_modules/app/composition/build_runtime_executor.py"
combined_fail_under = 85
branch_fail_under = 80

[[tool.graph_rag.coverage.risk_modules]]
path = "rag_modules/runtime/build_jobs/locks.py"
combined_fail_under = 85
branch_fail_under = 80
```

Every threshold is explicit. The parser does not supply hidden defaults. A future risk-file
addition or threshold change therefore remains visible in code review.

## Metric Semantics

The snapshot recalculates percentages from validated raw counts:

- branch percentage = `covered_branches / num_branches * 100`;
- combined percentage = `(covered_lines + covered_branches) /
  (num_statements + num_branches) * 100`.

The checker does not trust precomputed percentage fields in coverage.py JSON. Counts must be
non-negative integers, booleans are rejected as integers, covered counts cannot exceed totals,
and every configured risk file must have at least one branch.

Package matching uses a normalized directory prefix. Risk-file matching is exact after converting
backslashes to forward slashes and removing a leading `./`. Policy paths must be relative POSIX
paths without globs, `..`, empty segments, or absolute roots. Duplicate normalized risk paths are
invalid.

## Evaluation and Reporting Flow

The full pytest stage writes `coverage.json`, after which the coverage-policy stage:

1. reads and validates the TOML policy;
2. reads and validates the JSON report;
3. creates one package result followed by risk-file results in configuration order;
4. evaluates every valid rule, even after finding a threshold failure;
5. prints every result with percentages, raw counts, and required thresholds;
6. exits according to the result category.

The CLI exit codes are:

- `0`: every coverage rule passes;
- `1`: inputs are valid and at least one coverage threshold fails;
- `2`: policy or coverage input is invalid or unreadable.

Malformed TOML or JSON, missing mappings, missing configured files, absent branch data, invalid
counts, invalid paths, duplicate paths, missing thresholds, non-numeric thresholds, and thresholds
outside 0 through 100 all produce exit code 2. Threshold failures produce exit code 1. The local
gate stops after the coverage-policy stage fails, but the policy engine itself reports every failed
coverage rule before returning.

## Gate and Documentation Migration

- Rename the local-gate step from `branch_coverage` to `coverage_policy`.
- Replace every CI invocation of `python scripts/check_branch_coverage.py` with
  `python scripts/check_coverage_policy.py`.
- Update local-gate and enterprise-governance contract tests to require the new step and command.
- Update `README.md` and `docs/release_process.md` to document the three-layer policy, the nine
  risk files, the dual thresholds, and the rule for adding future risk files.
- Do not commit `coverage.json`, `.coverage`, pytest temporary directories, or evaluation reports.

## Risk-Path Test Matrix

### Coverage policy

Test strict TOML parsing, missing fields, numeric bounds, boolean rejection, path normalization,
path rejection, duplicates, exact file matching, package aggregation, raw-count validation,
missing branch data, simultaneous combined and branch failures, ordered multi-failure reporting,
and exit codes 0, 1, and 2.

### Fusion and constraint retrieval

Test empty ranked lists, same-source duplicates, cross-source fusion, rank ties, source priority,
`top_k` truncation, metadata preservation, score fallback, missing constraints, inactive
constraints, missing matcher, empty matcher results, evidence conversion, retrieval annotations,
and downstream exception propagation.

### Keyword extraction and BM25

Test blank and duplicate term removal, entity and topic fallbacks, relation-term expansion, output
limits, custom-dictionary absence and idempotent loading, empty tokenization, uninitialized search,
empty queries, score ordering, non-positive score filtering, metadata normalization, cache export,
valid cache restoration, invalid cache shapes, row-count mismatches, invalid token rows, and cache
construction exceptions.

### Hybrid driver and build executor

Test reuse of an existing driver, acquisition from an injected manager, missing-manager failure,
owned-driver close, non-owned-driver preservation, empty-driver close, build and rebuild argument
forwarding, manifest refresh, returned runtime identity, and missing-service failures.

### Milvus schema and client

Use contract-shaped in-memory fakes. Test schema fields, existing collection reuse, forced recreate,
collection creation, index creation, missing-collection-state failure, alias resolution, statistics
normalization, collection deletion, absent collection deletion, alias existence, direct existence,
collection loading, absent load target, state updates, client setup, embedding injection, close
semantics, and exception degradation for every externally backed operation. No live Milvus service
is used.

### File locking

Refactor `rag_modules/runtime/build_jobs/locks.py` so platform-specific system calls live behind
internal Windows and POSIX backend objects. `InterprocessFileLock` retains its public constructor,
context-manager behavior, and return values while owning only process-lock coordination, state
transitions, file lifetime, and cleanup.

Test normalized process-lock identity, repeated acquire and release, non-blocking same-process
contention, context acquisition failure, context-body exception cleanup, system-lock acquisition
failure cleanup, owned file closure, process-lock release, and Windows and POSIX lock/unlock flag
selection. Backend tests use injected contract-shaped OS modules and do not depend on the host
platform.

## Test Organization

Replace `tests/test_branch_coverage_gate.py` with focused policy tests under:

- `tests/test_coverage_policy_config.py`;
- `tests/test_coverage_policy_snapshot.py`;
- `tests/test_coverage_policy_cli.py`.

Add or extend focused behavior tests for each risk unit. Keep external-service fakes local to the
relevant test module unless two or more modules genuinely share the same contract.

All implementation work follows test-driven development: introduce one failing behavior test,
confirm the expected failure, implement the minimum behavior or boundary change, and rerun the
narrow slice before expanding verification.

## Completion Criteria

- Every configured risk file reports at least 85.00% combined coverage and 80.00% branch coverage.
- The coverage-policy CLI passes against a freshly generated full-suite `coverage.json`.
- The coverage.py global 75% combined gate and the 70% `rag_modules` package branch gate pass.
- Focused risk tests and policy tests pass.
- The complete `python -m pytest -q` suite passes with coverage generation enabled.
- `pre-commit run --all-files` passes after inspecting any formatter changes.
- `python scripts/release_gate.py` passes.
- Documentation and CI contract tests describe and enforce the new command and policy.
- No dependency locks, public RAG APIs, generated reports, or unrelated files change.

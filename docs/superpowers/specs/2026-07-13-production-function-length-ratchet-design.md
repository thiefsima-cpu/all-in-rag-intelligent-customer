# Production Function Length Ratchet Design

**Status:** awaiting written-spec review

## Goal

Make every production function under `rag_modules/` no longer than 80 physical lines while
preserving runtime behavior, then enforce that limit with a repository-wide structural ratchet.

The implementation starts from the latest `development` baseline on branch
`codex/performance-hotspot-ratchet`. The baseline already contains the completed answer pipeline,
generation client streaming, entity index, and evidence extraction decompositions. This change
retains their stricter named ratchets and closes the remaining repository-wide gap.

## Baseline

At design time, the latest `development` contains 11 production functions over 80 lines:

| Lines | Production function |
| ---: | --- |
| 116 | `query_policy/parsers/runtime_defaults.py::_parse_semantic_defaults` |
| 114 | `contracts/query_plan.py::QueryPlan.from_dict` |
| 110 | `query_understanding/graph_intent.py::infer_query_semantic_profile` |
| 95 | `infra/milvus/writer.py::_MilvusWriterOperations.build_vector_index` |
| 94 | `query_understanding/planning/calibration.py::QueryPlanCalibrator.calibrate` |
| 92 | `generation/execution/engine.py::GenerationExecutionEngine.generate_with_trace` |
| 91 | `routing/strategies/graph.py::GraphRouteStrategy.execute` |
| 83 | `query_understanding/planning/rule_based.py::RuleBasedPlanner.plan` |
| 83 | `domain/shared/semantic_schema.py::infer_recipe_semantics` |
| 82 | `generation/execution/two_stage.py::TwoStageCompletionRunner.run` |
| 81 | `retrieval/hybrid_components.py::DefaultHybridRetrievalComponentFactory.build` |

This list is evidence for the initial RED state, not a permanent baseline allow-list.

## Constraints

- Preserve public APIs, public import paths, types, return values, ordering, traces, telemetry,
  retries, cancellation, fallbacks, error handling, and configuration semantics.
- Use Python `>=3.11,<3.12`; do not add dependencies or edit generated lock files.
- Keep focused changes inside the current owner module. Do not introduce forwarding modules,
  compatibility aliases, public collaborators, or aggregate facades.
- Prefer existing dataclasses, models, and collaborator patterns over ad hoc dictionaries.
- Preserve all existing stricter named hotspot limits in
  `tests/test_hotspot_function_ratchets.py`.
- Add or update behavior tests before each production refactor and verify the intended RED state.
- Do not modify `agent/`, generated data, storage, volumes, evaluation reports, or pytest caches.

## Chosen Approach

Add one repository-wide AST ratchet and reduce every current violation through small private
extractions in the owning file.

This is preferred over two rejected alternatives:

1. Package-by-package ratcheting would reduce each change slice but leave ungoverned production
   directories during the P0 program.
2. Moving every helper into a new module or collaborator would make functions smaller at the cost
   of unnecessary file fragmentation and new abstraction surface.

The implementation therefore keeps public entry functions as readable coordinators and extracts
only coherent private responsibilities.

## Ratchet Contract

### Scan scope

The general ratchet scans every `*.py` file recursively under `rag_modules/` and inspects every
`ast.FunctionDef` and `ast.AsyncFunctionDef`, including:

- module functions;
- instance, class, and static methods;
- nested functions and nested async functions;
- private and dunder functions.

Test helpers, scripts, docs, generated directories, and the independent `agent/` package are not
production scan targets for this ratchet.

### Line-count definition

The physical length of a function is:

```python
(node.end_lineno or node.lineno) - node.lineno + 1
```

This matches the existing named hotspot ratchet. Decorator lines are not included because
`ast.FunctionDef.lineno` starts at the `def` or `async def` line. Blank lines, comments, docstrings,
and wrapped expressions inside the function are included.

The default maximum is exactly 80 lines. The violation message includes the repository-relative
POSIX path, fully qualified function name, actual line count, and maximum.

### Explicit state-machine exceptions

The ratchet defines a single explicit mapping named `STATE_MACHINE_FUNCTION_ALLOWLIST` whose key
is `(relative_path, qualified_name)` and whose value is a non-empty justification beginning with
`"state machine:"`.

The exception contract is intentionally narrow:

- no wildcard paths or names;
- at most three entries;
- every entry must resolve to an existing function;
- every entry must still be over 80 lines, so stale exceptions fail;
- every reason must explicitly explain the state-machine invariant that would become less clear if
  split.

This P0 implementation ships with an empty allow-list. All 11 existing violations must be reduced
to 80 lines or fewer. The mechanism exists only for a future reviewed state-machine exception; it
is not a migration debt list.

### Existing strict limits

The existing named limits remain intact. A function with a named 25-, 35-, or 45-line limit must
satisfy that tighter limit as well as the global 80-line limit. The global test supplements rather
than replaces the current hotspot governance.

## Decomposition Design

### Declarative configuration and contract construction

`_parse_semantic_defaults()` remains the canonical constructor for
`QuerySemanticRuntimeDefaultsPolicy`. Bind the existing semantic integer and float readers to the
selected section so the constructor remains a direct, typed field mapping without repeated wrapped
arguments. Do not change field names, readers, defaults, or validation behavior.

`QueryPlan.from_dict()` remains the public deserialization constructor. Extract private typed
helpers for semantic-profile resolution, strategy resolution, graph-query-type resolution, and
keyword/entity selection. Validation errors must retain their current order and exact strings.
Constraint mutation, clamping, relation filtering, fallback values, and `raw_plan` copying remain
unchanged.

`DefaultHybridRetrievalComponentFactory.build()` remains the public composition entry point.
Extract private construction stages around the existing typed components so object identity and
dependency wiring do not change. Do not introduce a second factory hierarchy or public assembly
contract.

### Query-understanding flow

`infer_query_semantic_profile()` becomes a coordinator for entity resolution, topic selection,
constraint/recommendation signals, and score construction. Private helpers return existing domain
types or small private dataclasses where multiple values must remain grouped. Candidate order,
deduplication, limits, marker hit order, score inputs, and reasoning thresholds remain unchanged.

`QueryPlanCalibrator.calibrate()` delegates profile application, strategy/query-type validation,
missing keyword/entity fill, graph source fallback, and max-depth clamping to private methods.
Mutation order remains observable through validation errors and must not change.

`RuleBasedPlanner.plan()` delegates source-entity selection and final plan construction. Strategy
resolution, complexity/intensity maxima, fallback keywords, limits, planner mode, confidence, and
fallback reason remain unchanged.

### Online generation and retrieval orchestration

`GenerationExecutionEngine.generate_with_trace()` delegates the selected generation attempt and
failure-to-evidence fallback to private methods. It must preserve usage reset, cancellation check
points, empty-evidence behavior, mode decision, package limiting, trace creation/finalization,
retry accounting, logging, and the distinction between `GenerationAttemptFailed`, cancellation,
budget exhaustion, and unexpected exceptions.

`GraphRouteStrategy.execute()` delegates the graph stage, empty-result hybrid fallback, and partial
result supplement stages to private helpers. It must preserve request copies, cancellation,
latencies, stage order/details, fallback labels, supplement sizing, document merging, and early
return behavior.

`TwoStageCompletionRunner.run()` delegates the primary plan/compose attempt and direct-model
fallback. A small private dataclass may carry latency and retry counters so retry draining happens
at the same logical points. Cancellation and budget failures continue to propagate without being
wrapped; nested fallback failure retains its exception chaining.

### Infrastructure and domain transformation

`_MilvusWriterOperations.build_vector_index()` delegates collection selection, entity
materialization, and batch insertion. It preserves empty-input validation, collection state,
forced recreation, embedding input order, field truncation, fallback IDs, batch size, flush/index/
load order, the two-second wait, logging, and false-on-operational-failure behavior.

`infer_recipe_semantics()` delegates contribution and technique-effect construction. It preserves
haystack order, tag extraction, unique ordering, relation keys, contribution expansion order, and
the returned dictionary schema.

## Test Design

### Structural RED and GREEN

First extend `tests/test_hotspot_function_ratchets.py` with the repository-wide scan. On the
unmodified baseline, the new test must fail with exactly the 11 violations listed above. The scan
and allow-list validation receive focused unit coverage, including nested/async qualification,
stale exceptions, invalid reasons, and the maximum exception count where practical without adding
test-only production hooks.

After each production slice, run the ratchet again and confirm its violation list shrinks only by
the intended targets. Completion requires zero global violations and an empty state-machine
allow-list.

### Behavior protection

Use the narrowest existing suites for each slice:

- runtime defaults and query plans: query-policy and query-semantics tests;
- graph intent, calibration, and rule planner: query-semantics and calibration branch tests;
- Milvus writer: `tests/test_milvus_writer.py` and relevant blue/green tests;
- generation engine and two-stage fallback: `tests/test_generation_executor.py`;
- graph routing: `tests/test_route_execution_strategies.py`;
- recipe semantics: `tests/test_semantic_schema_branches.py` and schema behavior tests;
- hybrid component wiring: retrieval service/factory and hybrid runtime tests.

Production behavior is unchanged, so snapshots and public payload expectations are not updated to
make a refactor pass. Any observed mismatch is investigated as a design or implementation defect.

## Implementation Order

1. Add the general structural ratchet and verify all 11 RED violations.
2. Reduce declarative construction hotspots.
3. Reduce query-understanding hotspots.
4. Reduce generation and routing orchestration hotspots.
5. Reduce Milvus, semantic transformation, and hybrid factory hotspots.
6. Confirm the global allow-list is empty and the named stricter ratchets remain green.
7. Run focused suites, Ruff, pre-commit, full pytest with a unique Windows base temp, release gate,
   and local gate.

This order keeps every commit independently reviewable and prevents a broad mechanical rewrite.

## Documentation

This is an internal structural governance change. No README or public workflow change is expected.
The design and implementation plan document the threshold and exception policy. If implementation
changes a public command, API, or operational expectation unexpectedly, stop and revise this design
before continuing.

## Completion Criteria

- Every function and async function under `rag_modules/` is 80 physical lines or fewer.
- `STATE_MACHINE_FUNCTION_ALLOWLIST` is empty.
- Existing named hotspot limits remain present and pass.
- All public behavior and public imports remain unchanged.
- Focused behavior suites pass after their corresponding refactors.
- Ruff and pre-commit pass without unreviewed rewrites.
- Full pytest, `python scripts/release_gate.py`, and `python scripts/local_gate.py` pass with fresh
  evidence, or any environment blocker is reported explicitly.
- Final git diff contains only the approved structural ratchet, focused production refactors,
  tests, and design/plan documentation.

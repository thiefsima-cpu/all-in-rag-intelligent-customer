# Remaining Hotspot Decomposition Design

**Status:** approved for implementation planning

## Goal

Reduce the remaining named review hotspots without changing runtime behavior:

- `rag_modules/graph_index/entity_index_builder.py::EntityIndexBuilder.build`
- `rag_modules/generation/clients/adapter.py::GenerationClientAdapter.stream_prompt`
- `rag_modules/application/answering/answer_pipeline.py::AnswerPipelineService.execute`
- `rag_modules/evidence_processing/extraction.py`
- `scripts/pressure_api_service.py`

The first four targets use private, in-file collaborator extraction. The pressure tool uses a
hard package cutover because its 1,276-line current file contains six independent capability
domains.

## Constraints

- Preserve all public production APIs, answer behavior, callback order, traces, telemetry,
  evidence ordering, pressure JSON schema, human output, and exit codes.
- Use Python `>=3.11,<3.12`; do not add dependencies or edit generated lock files.
- Keep the first four refactors local to their current owner modules. Do not add public types,
  protocols, factories, or forwarding modules for those extractions.
- Cut pressure imports over to canonical `scripts.pressure.*` modules. Do not re-export pressure
  data types or runner functions from `scripts.pressure_api_service.py` or
  `scripts.pressure.__init__`.
- Keep `python scripts/pressure_api_service.py --json` working as the documented direct script.
- Point the `graph-rag-pressure` console entry directly at `scripts.pressure.cli:main`.
- Keep the pressure tool local and deterministic. It must not contact real model providers,
  Neo4j, Milvus, or other external services.
- Add failing structural or import tests before production refactoring, then preserve the
  existing behavioral suites throughout the extraction.

## Chosen Approach

Use private helpers inside the four production modules and create a responsibility-oriented
package only for the pressure tool.

This avoids two rejected alternatives:

1. Creating a new collaborator class and module for every helper would strengthen isolation but
   would reintroduce the file fragmentation that the current branch has just removed.
2. Splitting the work into separate pressure and production phases would lower the scope of each
   batch but would repeat structural and repository-wide gates while leaving a partially reduced
   hotspot set between phases.

## Entity Index Builder

`EntityIndexBuilder.build()` remains the public orchestration method. It loops over recipes,
ingredients, and cooking steps, delegates each item to a private helper, logs completion, and
returns `store.entity_kv_store`.

Private responsibilities are:

- `_add_recipe_entity()` resolves the recipe identity and properties, builds the value, and adds
  it to the store.
- `_recipe_content_parts()` owns recipe display fields.
- `_recipe_index_keys()` owns recipe lookup keys and preserves `dedupe_preserve_order()`.
- `_add_ingredient_entity()` owns ingredient conversion and insertion.
- `_add_cooking_step_entity()` owns cooking-step conversion and insertion.

Entity IDs, fallback names, metadata shape, `entity_type`, extra keys, field order, and text
content remain byte-for-byte equivalent to the current behavior. Existing mojibake string
literals are moved without reinterpretation; character repair is outside this refactor.

## Generation Streaming Adapter

`GenerationClientAdapter.stream_prompt()` retains deadline calculation, retry orchestration, and
final exception propagation. It delegates one attempt and its stream consumption to private
methods.

A private `_StreamingAttemptState` dataclass records:

- whether the circuit breaker call started;
- whether any content was emitted;
- whether provider usage was reported;
- emitted text fragments used for estimated usage.

Private helpers own deadline resolution, opening a provider stream, consuming chunks, and waiting
before a retry. Generator delegation uses `yield from` so chunks retain their current order and
timing.

The following semantics are binding:

- `RequestCancelled` and `RequestBudgetExceeded` propagate without retry.
- Exhausted deadlines raise `GenerationLatencyBudgetExceeded` through the existing path.
- An empty provider stream raises `GenerationProviderResponseError` with failure code
  `generation_provider_empty_content`.
- An attempt that emitted content is never retried after a later failure.
- Circuit-breaker success and failure recording remain at the same logical points.
- Provider-reported usage wins; otherwise estimated usage uses the complete emitted text.
- Retry count tracking and retry sleep limits do not change.

## Answer Pipeline

`AnswerPipelineService.execute()` becomes a linear coordinator over private methods:

1. validate cancellation and emit the request prelude;
2. execute retrieval inside its telemetry span;
3. apply route resolution and route/graph traces to the state;
4. complete the no-evidence branch when required;
5. execute generation inside its telemetry span.

Retrieval and generation helpers own their complete span lifetime and attribute writes. State
application remains explicit rather than introducing an intermediate public DTO.

The refactor preserves:

- user-question, routing, strategy, document, generation-started, and fallback message order;
- optional routing explanation behavior;
- `AnswerContext.from_route_resolution()` construction;
- the exact no-evidence `GenerationSnapshot` fields and answer copy;
- streaming fallback behavior in `_generate_answer()`;
- retrieval and generation telemetry attribute names and values.

## Evidence Extraction

`extract_evidence_units()` remains the only public API and coordinates four stages:

1. coerce explicit `evidence_units` metadata into `EvidenceUnit` values;
2. expand primary, merged, or direct graph evidence payloads;
3. create a text fallback only when no earlier stage produced units;
4. deduplicate stably, convert to dictionaries, and truncate.

Private helpers own explicit-unit coercion, graph payload iteration, relationship conversion,
fallback construction, and final deduplication. `_graph_relationship_units()` is reduced by
delegating one relationship conversion to a focused helper.

Binding behavior includes:

- explicit units precede graph units;
- graph summaries precede relationship units for each payload;
- malformed relationship entries are skipped;
- at most 20 relationships are read from each graph payload;
- the first valid unit for a duplicate `unit_id` or claim wins;
- the public result contains at most 30 dictionaries in stable order;
- source, score, recipe identity, graph flags, and metadata fallback rules do not change.

## Pressure Package

Create this package:

```text
scripts/pressure/
|-- __init__.py
|-- scenario.py
|-- metrics.py
|-- thresholds.py
|-- reporter.py
|-- runner.py
`-- cli.py
```

### `scenario.py`

Owns `PressureScenario`, `DEFAULT_PRESSURE_SCENARIO`, and
`default_pressure_scenario()`. It normalizes all CLI and direct-call overrides into the canonical
immutable scenario contract.

### `metrics.py`

Owns `TraceMetrics`, `SseMetrics`, `ModelMetrics`, `RetrievalMetrics`, and `PressureMetrics`, plus
the private percentile calculation used by the runner. Serialization field names and rounding
remain unchanged.

### `thresholds.py`

Owns `PressureStatus`, `PressureThresholds`, `PressureCheck`,
`default_pressure_thresholds()`, and pressure-check evaluation. Maximum, minimum, warning,
request-accounting, model, retrieval, SSE, and trace checks retain their current names, operators,
messages, and ordering.

### `reporter.py`

Owns `PressureReport`, `build_pressure_report()`, human rendering, and JSON rendering. Reporting
does not execute scenarios or parse arguments. `PressureReport.exit_code` remains `1` only for a
`fail` report and `0` for `pass` or `warn`.

### `runner.py`

Owns the deterministic slow trace sink, diagnostics fixture, pressure test system, tracer
construction, derived synthetic metrics, normal concurrency execution, SSE execution, and
`run_pressure_test()`.

Mutable worker counters move into private run-state objects so worker functions do not retain a
large set of `nonlocal` variables. The runner returns a `PressureReport` and does not print.
Admission rejection counting, request allocation, thread naming, service shutdown, trace stats,
latency calculations, synthetic model metrics, and degraded retrieval metrics remain unchanged.

### `cli.py`

Owns `_parse_args()` and `main()`. It resolves defaults from `DEFAULT_PRESSURE_SCENARIO`, calls
`run_pressure_test()`, sends the report to the selected reporter, and returns the report exit code.

### Entrypoints

`scripts/pressure/__init__.py` contains only a package docstring and no aggregate exports.

`scripts/pressure_api_service.py` contains only repository-root path setup, import of
`scripts.pressure.cli.main`, and `SystemExit(main())` under the script guard. It defines no data
types, runner functions, reporters, or compatibility aliases and stays at or below 20 lines.

`pyproject.toml` changes the console script to:

```toml
graph-rag-pressure = "scripts.pressure.cli:main"
```

## Dependency Direction

The pressure modules follow this acyclic dependency direction:

```text
cli -> runner -> reporter -> thresholds -> metrics
 |        |          |            |          |
 `------> scenario <--+------------+----------+
```

`scenario` is foundational. `metrics` contains only metric contracts and calculation utilities.
`thresholds` consumes scenarios and metrics. `reporter` consumes those contracts and evaluated
checks. `runner` constructs reports. `cli` is the only argument and process boundary.

## Tests

### Structural RED tests

Extend `tests/test_hotspot_function_ratchets.py` before refactoring so the current checkout fails
these limits:

- `EntityIndexBuilder.build`: at most 25 lines;
- `GenerationClientAdapter.stream_prompt`: at most 35 lines;
- `AnswerPipelineService.execute`: at most 35 lines;
- `extract_evidence_units`: at most 35 lines;
- primary pressure runner orchestration functions: at most 45 lines.

Add an AST assertion that `scripts/pressure_api_service.py` is at most 20 lines and defines no
class or function. Add import-boundary assertions proving that pressure business symbols are
owned by their canonical modules and are absent from the old script and package root.

### Behavioral suites

- Entity behavior: `tests/test_graph_indexing_module.py`.
- Streaming behavior: `tests/test_generation_client.py` and
  `tests/test_generation_executor.py`.
- Answer behavior: `tests/test_answer_workflow.py` and application use-case tests.
- Evidence behavior: `tests/test_evidence_extraction.py`.

Split `tests/test_pressure_api_service.py` by capability and remove the old mixed test module:

- `tests/test_pressure_thresholds.py` covers check evaluation, report status, schema, and
  serialization.
- `tests/test_pressure_runner.py` covers default, saturation, SSE, model-budget, retrieval, trace,
  and accounting scenarios.
- `tests/test_pressure_cli.py` covers parser defaults, JSON and human output, direct-script
  execution, console entrypoint ownership, and exit codes.

No snapshot or expected payload changes are permitted unless a test exposes a current payload
that was not represented accurately before this refactor. Such a mismatch is treated as a design
issue rather than silently updating the expectation.

## Documentation

Keep the documented direct command unchanged in `README.md` and
`docs/api_capacity_and_pressure_thresholds.md`. Update only architecture or import-owner wording
needed to describe the new package and console entrypoint. Historical plans and specs are not
rewritten.

## Verification

Run the narrowest suite after each extraction, then widen in this order:

1. all new pressure test modules and each target's focused behavioral tests;
2. `tests/test_hotspot_function_ratchets.py`, module-boundary tests, public-manifest tests, and
   entrypoint tests;
3. Ruff on every touched production, script, test, and documentation-adjacent Python file;
4. repository pre-commit hooks and strict type checks used by the local gate;
5. complete pytest with a unique `--basetemp` directory on Windows when needed;
6. `python scripts/release_gate.py`;
7. `python scripts/local_gate.py`.

Completion requires fresh passing evidence for the focused tests, structural ratchets, full test
suite, release gate, and local gate. Any skipped or environment-blocked check must be reported
explicitly.

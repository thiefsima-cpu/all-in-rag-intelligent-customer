# Policy Versioning Governance Design

## Goal

Make prompt, routing, scoring, relation strategy, and graph-question decomposition policy a
versioned resource bundle instead of scattered Python constants.

This is an intentional internal breaking refactor. The system should have one authoritative policy
schema, one typed loader, and one metadata record that flows into traces and eval reports. The old
unversioned resource shape and inline Python fallbacks should be removed, not kept as compatibility
bridges.

## Current State

`rag_modules/query_policy/defaults.json` already holds many lexical term sets, relation markers,
entity-linker priorities, regex rules, and runtime defaults. `rag_modules/query_policy/planner_prompt.txt`
holds the query-planning prompt template.

Important policy still lives in code:

- Generation plan, compose, and direct-answer prompts are embedded in
  `rag_modules/generation/prompt_builder.py`.
- Rule-based generation planning text, fallback outline, cautions, missing-information messages,
  and answer-type keyword checks live in `rag_modules/generation/planner.py` and
  `rag_modules/generation/prompt_builder.py`.
- Graph sub-question templates live in `rag_modules/graph/query_resolution.py`.
- Scoring and routing still contain unversioned formula details, such as structural-hit
  contribution factors and high-pressure generation margins.
- Trace snapshots and eval reports expose profile/model metadata but do not record the prompt or
  policy version that shaped the answer.

The consequence is that enterprise scenarios cannot compare evaluation runs cleanly when policy
changes. A prompt edit, routing-threshold edit, or graph decomposition edit can change behavior
without leaving a first-class version trail in traces or reports.

## Scope

In scope:

- Replace the current unversioned query-policy files with a versioned policy bundle.
- Move all prompt templates, generation rule-plan templates, graph sub-question templates,
  scoring formula parameters, routing rule parameters, relation strategy templates, and relation
  priorities into the policy bundle.
- Replace ad hoc dictionary access with typed policy dataclasses.
- Propagate policy metadata through route, graph, generation, query trace, API debug payloads, and
  eval reports.
- Update tests, fixtures, and prompt snapshots to the new policy contract.
- Remove inline Python prompt/policy fallbacks once the resource bundle is validated.

Out of scope:

- Runtime download or remote policy management.
- A UI for editing policies.
- Preserving the old `defaults.json` schema.
- Preserving old internal trace payloads for replay.
- Moving environment-specific infrastructure settings into the policy bundle.
- Adding runtime dependencies.

## Hard Constraints

- No compatibility loader for the old policy schema.
- No inline production prompt fallback.
- No silent empty `policy_version`, `prompt_version`, or `policy_hash` in newly produced trace or
  eval payloads.
- No profile TOML duplication of prompt bodies or lexical term sets.
- No broad public API rename unless a debug schema needs to expose policy metadata.
- No behavior-changing policy value may remain as a free-floating module-level literal in routing,
  scoring, graph decomposition, or generation prompting.

## Resource Layout

Replace the unversioned policy files with a bundle-oriented layout:

```text
rag_modules/query_policy/
  __init__.py
  loader.py
  models.py
  resources/
    c9-default-v1/
      manifest.json
      policy.json
      prompts/
        query_planner.txt
        answer_plan.txt
        answer_compose.txt
        answer_direct.txt
```

`manifest.json` owns metadata and references:

- `schema_version`, for loader/schema compatibility.
- `policy_version`, for routing, scoring, graph, relation, and rule-plan semantics.
- `prompt_version`, for query-planning and answer-generation prompt text.
- `name`, `description`, and optional `scenario`.
- Relative paths to `policy.json` and prompt templates.

The loader computes:

- `policy_hash`, a stable SHA-256 over normalized manifest, policy JSON, and all referenced prompt
  files.
- `prompt_hash`, a stable SHA-256 over the prompt template files.

The hashes are computed at load time and never hand-maintained in resource files.

## Policy Schema

`policy.json` should be structured around policy concepts, not current Python file names:

- `lexicon`: term sets, regex rules, cleanup patterns, stopwords, graph source prefixes/suffixes.
- `relations`: graph relation types, semantic relation hints, relation query markers, relation
  index keywords, relation index suffix templates, preferred relation exclusions, relation
  evidence-goal mappings, and entity-linker priorities.
- `scoring`: relationship intensity formula, complexity formula, boost formula, normalization
  limits, and numeric bounds.
- `routing`: graph-first rules, meaningful-constraint fields, strategy resolution thresholds,
  query-type resolution rules, source-entity fallback order, and validation-error labels.
- `graph`: max-depth profiles, max-node profiles, adaptive traversal profiles, fallback name
  length, sub-question templates, template activation conditions, reasoning relation groups,
  comparison markers, and semantic relation key specs.
- `generation`: direct-vs-two-stage decision rules, high-pressure margin, decision reasons,
  answer-type inference rules, relation-explanation markers, rule-plan outline, cautions,
  missing-information templates, and prompt metadata defaults.
- `runtime_defaults`: planner, retrieval candidate, candidate-source, and postprocess defaults
  that are genuine runtime knobs rather than semantic text.

Existing relation names and strategy values should stay string-stable because they are domain
vocabularies already covered by enums and public traces. The schema shape may break; the value
vocabularies should not change unless the policy intentionally changes behavior.

## Typed Loader

Create `rag_modules/query_policy/models.py` with dataclasses for:

- `PolicyMetadata`
- `QueryPolicyBundle`
- `LexiconPolicy`
- `RelationPolicy`
- `ScoringPolicy`
- `RoutingPolicy`
- `GraphPolicy`
- `GenerationPolicy`
- `PromptTemplates`

The loader should:

1. Read the default bundle manifest.
2. Load and validate `policy.json`.
3. Load and validate all prompt templates.
4. Verify required placeholders for each prompt template.
5. Verify relation references point to declared relation types.
6. Verify strategy references point to declared route strategies.
7. Verify query-type references point to declared graph query types.
8. Compute metadata hashes.
9. Return one immutable `QueryPolicyBundle`.

Validation should fail fast with a `PolicyLoadError` that includes the bundle path, field path, and
reason. There should be no fallback to hardcoded defaults after a resource error.

`get_query_policy()` remains only as the package-level typed bundle entry point. It should return
the new `QueryPolicyBundle`, not a legacy JSON-shaped policy. Old ad hoc accessors that expose raw
JSON-shaped dictionaries should be removed or renamed to typed accessors.

## Configuration Boundary

Profiles remain runtime/environment configuration. They may still override numeric runtime
settings through the existing `query_understanding` and `generation` configuration sections, but
they should not duplicate prompt bodies, term sets, relation mappings, or graph sub-question text.

Add one policy selector to configuration, for example:

```toml
[query_understanding.policy]
bundle = "c9-default-v1"
```

The selector chooses a bundled resource under `rag_modules/query_policy/resources/`. A separate
`bundle_path` override may be added for local development and private enterprise bundles, but the
configured path must resolve to a complete manifest-driven bundle and pass the same validation.

Runtime settings should be built from:

1. Policy resource defaults.
2. Profile/env/explicit config overrides for runtime knobs.

This preserves the distinction:

- Policy bundle: product semantics and versioned behavior.
- Profile: deployment shape, latency/cost knobs, and environment-specific overrides.

This keeps enterprise multi-scenario behavior explicit: two profiles can share infrastructure
settings while selecting different policy bundles, and eval reports can compare those runs through
policy metadata rather than through profile names alone.

## Routing And Scoring Refactor

`rag_modules/query_understanding/scoring.py` should stop containing formula constants such as
structural-hit contribution factors. It should consume `ScoringPolicy` plus runtime override
values from `QuerySemanticRuntimeSettings`.

`rag_modules/query_understanding/graph_intent.py` and
`rag_modules/query_understanding/planning/calibration.py` should consume `RoutingPolicy` and
`GraphPolicy` for:

- Query-type max-depth and max-node profiles.
- High-intensity thresholds.
- Graph-first query-type sets.
- Meaningful-constraint field lists.
- Strategy resolution thresholds.
- Source-entity fallback order.
- Validation-error message keys.

The calibrator should not hardcode strategy decision tables. It should apply typed routing rules
loaded from the policy bundle and emit the configured validation reason labels.

## Generation Refactor

`GenerationPromptBuilder` should render the prompt templates loaded from policy resources:

- `answer_plan.txt`
- `answer_compose.txt`
- `answer_direct.txt`

The prompt builder should pass structured render variables such as question, evidence summary,
evidence text, plan JSON, and prompt metadata. Missing placeholders should fail during policy load,
not at request time.

Rule-based answer planning should move all configurable language and keyword policy into
`GenerationPolicy`:

- Answer type definitions and marker terms.
- Relation-explanation marker terms.
- Default outline.
- Graph-evidence caution.
- Missing relation-evidence message.
- Sparse-evidence message.
- Missing-information caution.
- Fallback plan outline for malformed LLM planner output.

`rag_modules/generation/decision.py` should consume generation decision policy for:

- Strategy-to-generation-mode rules.
- Combined-strategy reasoning pressure rule.
- High-complexity or dense-relation margin.
- Decision reason strings.
- Evidence-limit setting names.

No direct-vs-two-stage threshold arithmetic should remain as hidden literals.

## Graph Sub-Question Refactor

`GraphQueryFactory.decompose_graph_question()` should become a policy-driven renderer.

`GraphPolicy.sub_questions` should define ordered rules with:

- `id`
- activation condition, such as entities present, relation type intersects, constraints present,
  relationship intensity threshold, query marker terms, or fallback
- template text
- max emitted questions

The graph trace should record both rendered `sub_questions` and the policy version that produced
them. If no non-fallback rule matches, exactly one configured fallback template should render.

## Trace Contract

Add a small policy metadata DTO to runtime contracts:

```text
PolicySnapshot
  schema_version
  policy_version
  prompt_version
  policy_hash
  prompt_hash
  bundle_name
```

Newly produced traces should include policy metadata in:

- `RouteSnapshot.policy`
- `GraphRetrievalSnapshot.policy`
- `GenerationSnapshot.policy`
- `QueryTraceEvent.policy`

`RouteTraceRecorder.record_plan()` should include the policy snapshot in the plan stage details as
well as on the route snapshot. `GenerationPromptBuilder.render_*()` should include prompt and
policy metadata on `RenderedPrompt.metadata`; execution should copy it into `GenerationSnapshot`.

`QueryTracer` should normalize one top-level `PolicySnapshot` from the generation, route, and graph
snapshots. If snapshots disagree or the policy snapshot is missing during a real workflow, the
trace should carry a contract failure reason and the relevant tests should fail. Existing tests
that manually construct trace payloads should be migrated to provide explicit policy metadata
instead of relying on empty defaults.

## Eval Report Contract

`scripts/eval_queries.py` should include policy metadata in:

- Report top level: `policy`.
- Each result: `policy`.
- Markdown summary lines: policy version, prompt version, policy hash, prompt hash.

When `generate=false`, the eval result should use route/graph policy metadata. When
`generate=true`, it should use generation/query trace metadata. A missing policy snapshot in a new
system response should be treated as an eval contract failure.

Release-gate and quality eval thresholds do not need new numeric gates in this pass, but the report
schema should make policy identity unavoidable for run comparison.

## API Debug Payload

Public answer payloads should stay focused. Debug answer payloads and schemas should expose the
policy metadata already present in traces.

If the existing response model serializes `traces.generation_trace`, `traces.route_trace`, and
`traces.graph_trace`, those nested trace objects should include `policy`. A top-level debug trace
event should include `policy` through `QueryTraceEvent`.

## Error Handling

Startup or first policy access should fail if:

- Manifest is missing required metadata.
- Schema version is unsupported.
- Policy JSON is malformed.
- Required prompt files are missing.
- Required placeholders are absent.
- A rule references an unknown relation type, graph query type, route strategy, generation mode,
  or runtime setting key.
- A numeric rule is outside its declared bounds.

Errors should name the bundle path and logical field path. They should not include raw prompts or
user query content.

## Testing

Use test-first implementation. Focused tests should cover:

- Policy loader rejects the old unversioned schema.
- Policy loader exposes schema version, policy version, prompt version, policy hash, and prompt
  hash.
- Policy loader rejects missing prompt placeholders.
- Policy loader rejects incomplete graph reasoning policy and unknown relation references.
- Scoring uses policy-provided formula parameters instead of hidden constants.
- Routing calibration uses policy-provided graph-first and strategy rules.
- Generation prompt rendering uses resource templates and records policy metadata.
- Rule-based generation planning uses policy answer-type and missing-information templates.
- Generation decision uses policy high-pressure margin and reason strings.
- Graph sub-question rendering uses policy rule templates and fallback template.
- Relation index and graph reasoning consumers use policy relation keys, suffix templates, and
  reasoning relation groups instead of module-level strategy literals.
- Route, graph, generation, and query trace snapshots serialize policy metadata.
- Eval report and summary include policy metadata and fail when a generated response lacks it.
- API debug schemas expose policy metadata through trace models.
- Prompt snapshot fixtures are updated once to the resource-rendered templates.

Run focused tests first:

```powershell
python -m pytest tests/test_query_policy.py tests/test_query_semantics.py tests/test_generation_prompt_contract.py tests/test_generation_executor.py tests/test_graph_retrieval_executor.py tests/test_query_tracer.py tests/test_eval_queries.py -q
```

Then run boundary/API tests because trace DTOs and debug schemas change:

```powershell
python -m pytest tests/test_answer_response_mapping.py tests/test_api_app.py tests/test_public_surface_boundaries.py tests/test_public_api_manifest.py -q
```

Before declaring implementation complete, run:

```powershell
pre-commit run --all-files
python scripts/release_gate.py
```

## Acceptance Criteria

- No production prompt bodies remain embedded in Python.
- No routing/scoring behavior constants remain as unversioned module-level literals.
- Graph sub-question text comes from the policy bundle.
- Generation rule-plan text and answer-type markers come from the policy bundle.
- Profiles select policy bundles by name or explicit development path without copying policy
  content into TOML.
- Query planning, routing, graph retrieval, generation, trace, and eval all report the same policy
  metadata for a request.
- Eval reports can distinguish two runs that use the same profile but different policy bundles.
- Invalid policy resources fail fast with actionable field-path errors.
- The old unversioned policy schema is rejected by tests.
- Focused tests, API/debug schema tests, public surface tests, pre-commit, and release gate pass.

## Migration Notes

This refactor should land as one coherent internal migration:

1. Add the new typed policy resource contract and bundle files.
2. Add failing tests for loader metadata, prompt rendering, policy-driven scoring/routing, trace
   metadata, and eval metadata.
3. Replace Python inline constants and prompt bodies with typed policy access.
4. Update trace DTOs and API debug schemas.
5. Update eval reports and prompt snapshots.
6. Remove old policy files and any compatibility loader path.
7. Run the focused and broad verification commands.

The result should be a clean policy boundary rather than an incremental patch layer.

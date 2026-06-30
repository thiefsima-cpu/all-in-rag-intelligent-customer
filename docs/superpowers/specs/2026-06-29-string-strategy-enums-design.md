# String Strategy Enum Convergence Design

## Goal

Reduce spelling-driven runtime errors by converging four named string strategy families into
typed Enum boundaries while preserving existing JSON, profile, API, and trace payload values.

The scope is limited to:

- Artifact manifest stages.
- Route strategy values.
- Retrieval candidate-source degradation strategy values.
- Planner mode values.
- Generation mode values.
- Graph query type values.

Answer style, fallback reasons, trace status, and other string classifications are intentionally
out of scope for this pass.

## Current State

Route strategy already has a canonical `SearchStrategy` enum in `rag_modules.runtime`, but
several query-planning DTOs and rule/calibration paths still pass plain strings. Artifact stages
are centralized as constants in `rag_modules.runtime.artifacts.manifest`, but
`ArtifactManifest.stage` is still an untyped string. Retrieval candidate-source degradation
strategy is normalized in two places with duplicated string sets. Planner mode is normalized as a
string in generation settings and assigned as raw strings in query-planning traces.

The public wire format is already string-based and should stay that way. The desired change is
internal typing and earlier validation, not a public payload migration.

## Approach

Use local `str, Enum` classes at the domain boundary that owns each vocabulary:

- `ArtifactStage` in `rag_modules.runtime.artifacts.manifest`.
- Existing `SearchStrategy` for route strategy.
- `CandidateSourceDegradationStrategy` in retrieval candidate-source settings/generator code.
- `GenerationPlannerMode` for generation planner settings.
- `QueryPlannerMode` for query-planning runtime trace mode values.
- `GenerationMode` for direct/two-stage/empty generation execution modes.
- `GraphQueryType` for query semantic profile and query plan graph-query type values, with the
  graph package's existing `QueryType` kept as a compatibility alias.

Enums should accept existing string values during construction and expose `.value` when payloads
are serialized. Existing `ARTIFACT_STAGE_*` and degradation constants may remain as compatibility
aliases to avoid broad call-site churn, but their values should come from the enum.

## Compatibility

`ArtifactManifest.to_dict()`, `QueryPlan.to_dict()`, answer response DTOs, route traces, and
configuration `to_dict()` should continue emitting strings such as `"ready"`, `"combined"`,
`"fail_fast"`, `"rule"`, `"direct"`, and `"multi_hop"`.

Existing profiles and environment variables should continue using the same string values. Invalid
configuration values should fail during configuration or runtime-settings construction with a
message that lists supported values. Invalid LLM-produced route strategies should keep the current
safe fallback behavior in `QueryPlan.from_dict()`, but valid strategies should normalize through
`SearchStrategy`.

## Components

### Artifact Stage

`ArtifactManifest.stage` should accept `ArtifactStage | str` and normalize in `__post_init__`.
Known stage checks (`is_ready`, `is_failed`, `is_in_progress`, `is_invalid`) should compare against
enum values or enum sets. `from_dict()` and `evolve()` should accept strings and enums.

Unknown persisted manifest stages should still load as the default missing stage or fail safely
according to the existing manifest-store behavior; this pass should not introduce a crash loop for
old or corrupt manifests.

### Route Strategy

`SearchStrategy` remains the canonical enum. `QueryPlan.strategy` should normalize valid strings
to `SearchStrategy` internally and serialize back to `.value`. Calibration and rule-based planning
should use enum values or helper conversion instead of repeating raw string literals.

Invalid planner output should continue adding `invalid_strategy:<value>` to validation errors and
fall back to the existing combined-or-hybrid decision.

### Candidate-Source Degradation Strategy

Introduce one enum for `"continue"` and `"fail_fast"` and reuse it from both
`RetrievalCandidateSourceSettings` and `RetrievalCandidateGenerator`. Configuration should reject
unsupported values during model validation rather than letting only the generator catch them later.

The generator should accept either enum or string for constructor compatibility and store the enum
internally.

### Planner Mode

Generation planner mode controls answer-plan construction and supports `"rule"`, `"hybrid"`, and
`"llm"`. Invalid values should be rejected in generation config/runtime settings instead of
silently taking the LLM branch.

Query planner mode is trace metadata for query planning and supports `"llm"`, `"rule_based"`,
`"fast_rule"`, and `"fallback_rule"`. `QueryPlan` should normalize these values and serialize
strings. Rule and fallback assignments should use enum values.

### Generation Mode

Generation mode supports `"direct"`, `"two_stage"`, and the internal empty-evidence trace mode
`"empty"`. `GenerationDecision` and `GenerationTrace` should normalize known mode values to
`GenerationMode`, while `GenerationSnapshot` should normalize known values but preserve unknown
historical trace strings when loading old payloads. All API, trace, telemetry, and smoke-report
payloads should continue emitting plain strings via a value helper.

### Graph Query Type

`GraphQueryType` should be owned by the contract kernel so query planning, semantic profiles,
route traces, and graph retrieval share one vocabulary without making contracts depend on graph
feature packages. `QuerySemanticProfile.query_type` and `QueryPlan.graph_query_type` should
normalize valid values to the enum and serialize strings. Invalid LLM-produced graph query types
should keep the existing validation error and fallback behavior.

The graph package should keep `QueryType` as a compatibility alias to avoid broad executor and
retrieval call-site churn.

## Testing

Focused tests should be added before implementation:

- Artifact manifests accept enum and string stages and still serialize strings.
- Retrieval config rejects an invalid `candidate_source_degradation_strategy` and accepts
  `"fail_fast"`.
- Retrieval candidate generator stores the degradation strategy as the enum but preserves
  fail-fast behavior.
- Generation config/runtime settings reject invalid planner modes and normalize valid modes.
- Query plans normalize valid route strategies and planner modes while preserving existing invalid
  route fallback behavior.
- Generation decisions, traces, and snapshots normalize mode values while serializing strings.
- Query semantic profiles and query plans normalize graph query types while preserving invalid
  planner-output fallback behavior.

Run the narrow test files first, then expand to related API/runtime tests if shared behavior is
touched.

## Non-Goals

- No public API field renames.
- No profile syntax migration.
- No broad refactor of trace status, answer type, answer style, or fallback reason strings.
- No new runtime dependencies.

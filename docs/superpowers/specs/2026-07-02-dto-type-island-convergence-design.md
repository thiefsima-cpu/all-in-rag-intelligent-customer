# DTO Type Island Convergence Design

## Goal

Expand the strict type-contract island by retiring internal `Any` and
`dict[str, Any]` payloads from graph, build-pipeline graph preparation, query
policy, and runtime diagnostics. This is a boundary rewrite, not a compatibility
shim: stable internal data moves to dataclasses or strict Pydantic models, and
callers are updated to use those contracts directly.

## Scope

This design covers:

- `rag_modules/app/diagnostics.py` and
  `rag_modules/app/services/runtime_diagnostics_service.py`.
- `rag_modules/query_policy/models.py` and `rag_modules/query_policy/loader.py`.
- Graph cache and graph retrieval DTO modules where payloads already have stable
  fields.
- `rag_modules/build_pipeline/graph_preparation/` models, statistics, loader,
  module, and document builder boundaries.
- `tests/test_type_contract_ratchets.py`, `tests/typecheck/type_contracts.py`,
  and the focused mypy override list in `pyproject.toml`.

This design does not rewrite public FastAPI response shapes, change the policy
bundle JSON schema for users, or make the full repository strict. It does remove
old internal dict-shaped contracts in the touched slice.

## Boundary Rules

Use explicit DTOs inside the application after data crosses an external or
adapter boundary.

Allowed dynamic boundaries:

- JSON file loading in `query_policy.loader` before validation.
- Neo4j driver records and node/relationship properties at the adapter edge.
- FastAPI/OpenAPI serialization and JSON response builders.
- Artifact metadata that is intentionally user- or build-tool-defined.

Not allowed inside the new island:

- Dataclass fields typed as `dict[str, Any]` or `Dict[str, Any]`.
- Return values such as `Dict[str, Any]` for stable diagnostics, stats, policy,
  or graph DTOs.
- Functions that accept both old dict payloads and new DTOs for the same
  internal concept.
- "Best effort" compatibility methods that hide migration work from callers.

For genuinely open JSON payloads, use the existing runtime JSON aliases
(`JsonObject`, `JsonValue`) or add a narrowly named alias in the owning module.
These aliases mark true serialization boundaries; they are not a substitute for
DTOs when fields are known.

## Runtime Diagnostics

`StartupDiagnostics`, `SystemStatsDiagnostics`, and
`ArtifactManifestDiagnostics` remain dataclasses, but their open fields become
typed snapshots:

- `ModelDiagnostics` for model names.
- `TraceStatsDiagnostics` for dropped, queued, emitted, failed, and async trace
  counters that are actually displayed and serialized.
- `RetrievalRuntimeProfileDiagnostics` for the stable planner/runtime profile
  fields used by stats endpoints.
- `DataStatsDiagnostics`, `IndexStatsDiagnostics`, and `RouteStatsDiagnostics`
  for the stable counters consumed by the API and console stats views.
- `ArtifactBuildMetadataDiagnostics` for known manifest build metadata such as
  profile name, path, and hash, with a JSON object only for explicitly open
  extension metadata.

The service layer converts adapter stats into these DTOs once. Downstream code
uses attributes, not dictionary lookups. `to_dict()` remains only as the public
serialization method and returns a JSON-shaped mapping.

## Query Policy

The policy bundle keeps its external JSON schema, but the loader validates JSON
into typed policy dataclasses without preserving raw nested dicts.

New or refined DTOs:

- `GraphSubQuestionPolicy` with `id`, `template`, and a typed `when` predicate.
- `GraphSubQuestionCondition` with explicit fields for current supported
  predicates, such as fallback, query types, relation types, and constraints.
- `GenerationAnswerTypePolicy` for answer type markers and future stable
  fields.
- `GenerationRulePlanPolicy` for outline and caution templates.
- `GenerationDecisionPolicy` and `GenerationDecisionReasonsPolicy`.
- `RuntimeDefaultsPolicy` sections for planner and semantics settings.

`QueryPolicyBundle.runtime_section()` is retired for internal callers in the
touched slice. Callers use typed properties such as `runtime_defaults.planner`
or `runtime_defaults.semantics`. If a caller needs a serialized view, it calls a
DTO `to_dict()` method at the boundary.

## Graph DTOs

Graph cache stats and retrieval DTOs should describe graph data explicitly:

- `GraphCacheEntityStats` replaces entity dictionaries in cache stats.
- `GraphNodeSnapshot` and `GraphRelationshipSnapshot` replace stable node and
  relationship dictionaries where graph retrieval and evidence builders exchange
  subgraph data.
- `GraphPath` and `KnowledgeSubgraph` use those snapshots rather than raw
  dictionaries for nodes and relationships.

Neo4j properties remain a JSON object at the adapter edge because graph schema
properties are data-driven. Once a field is promoted into business logic, it is
copied into a DTO attribute instead of read repeatedly from a raw property map.

## Build-Pipeline Graph Preparation

Build-time graph preparation currently mixes stable recipe/chunk statistics with
raw properties. The rewrite separates them:

- `GraphNode.properties` and `GraphRelation.properties` use `JsonObject`.
- `PreparedRecipeDocumentInput`, `PreparedIngredientInput`, and
  `PreparedStepInput` model the fields the document builder actually consumes.
- `GraphPreparationStats` replaces the statistics dictionary returned by
  `GraphPreparationStatisticsService.build`.
- `GraphPreparationModule.get_statistics()` returns `GraphPreparationStats`.

Callers that print or expose stats serialize `GraphPreparationStats` at the
presentation/API boundary. Internal tests assert attributes rather than dict
keys.

## Mypy and Ratchets

Extend `tests/test_type_contract_ratchets.py` to include the newly converted
files. The ratchet should fail on explicit `Any` in these modules.

Extend the strict mypy override in `pyproject.toml` to include:

- `rag_modules.app.diagnostics`
- `rag_modules.app.services.runtime_diagnostics_service`
- `rag_modules.query_policy.models`
- `rag_modules.query_policy.loader`
- `rag_modules.graph.cache_stats`
- `rag_modules.graph.retrieval_types`
- `rag_modules.graph.retrieval_postprocess`
- `rag_modules.graph.evidence_builder`
- `rag_modules.graph.reasoning_strategy`
- `rag_modules.build_pipeline.graph_preparation.models`
- `rag_modules.build_pipeline.graph_preparation.statistics`
- `rag_modules.build_pipeline.graph_preparation.document_builder`
- `rag_modules.build_pipeline.graph_preparation.loader`
- `rag_modules.build_pipeline.graph_preparation.module`

The strict island keeps the existing flags:

- `check_untyped_defs = true`
- `disallow_untyped_defs = true`
- `warn_return_any = true`
- `warn_unused_ignores = true`
- `no_implicit_optional = true`

## Testing

Use TDD for each slice:

- Add ratchet tests first and watch them fail on explicit `Any`.
- Add focused behavior tests that assert DTO attributes and serialization output.
- Add typecheck fixtures for representative concrete callers.
- Convert production code only after the relevant test is red.
- Run narrow tests for each touched subsystem before broadening to mypy and
  pre-commit or equivalent Ruff checks.

Recommended narrow checks:

- `python -m pytest tests/test_runtime_diagnostics_service.py tests/test_type_contract_ratchets.py -q`
- `python -m pytest tests/test_query_policy.py tests/test_type_contract_ratchets.py -q`
- `python -m pytest tests/test_graph_cache_stats.py tests/test_graph_retrieval_executor.py tests/test_type_contract_ratchets.py -q`
- `python -m pytest tests/test_graph_data_preparation_module.py tests/test_build_pipeline_stats_presenter.py tests/test_type_contract_ratchets.py -q`
- `python -m mypy --config-file pyproject.toml`

## Migration Strategy

Implement in four independent commits or review chunks:

1. Runtime diagnostics DTOs and strict ratchet.
2. Query policy typed nested sections and caller updates.
3. Graph cache/retrieval DTOs with Neo4j properties isolated.
4. Build-pipeline graph-preparation DTOs and stats presenter updates.

Each chunk removes the old internal dict contract in its slice before moving to
the next. No chunk should add temporary dual APIs.

## Acceptance Criteria

- The expanded island has no explicit `Any` in ratcheted modules.
- Stable internal payloads in the touched slices are dataclasses or Pydantic
  models, not dicts.
- Dynamic JSON remains only at documented external or adapter boundaries.
- Existing public API JSON shapes remain compatible unless a test explicitly
  changes the contract.
- Focused behavior tests, `tests/test_type_contract_ratchets.py`, and mypy pass.

# Configuration, Contract, and Kernel Convergence Design

Status: implemented

Date: 2026-07-22

## Context

The current production package contains 417 Python files and 52,451 physical lines on the
`development` branch. An AST inventory finds 155 `Protocol` declarations, 95 non-`__init__.py`
modules below 60 lines, and 367 `Any` name nodes. These numbers are signals rather than isolated
defects: the costly cases combine horizontal file splitting, duplicated input shapes, one-call
delegation, and type erasure at boundaries.

This is the first dependency-ordered wave of a repository-wide convergence program. Later waves
will cover application/runtime composition, retrieval and generation, graph and routing, and the
remaining infrastructure and API surfaces. Each wave must close a dependency cluster completely
and lower structural ratchets before the next wave starts.

This wave covers `rag_modules.configuration`, `rag_modules.contracts`, and `rag_modules.kernel`,
plus repository callers that must move atomically when those low-level boundaries change. It uses
a hard cutover: deleted Python paths, deprecated DTO fields, and retired environment names fail
instead of forwarding, warning, or silently falling back.

## Goals

1. Replace configuration's section-oriented packages with responsibility-owned modules and one
   production loading path.
2. Keep only stable shared DTOs and real substitution ports in the contract kernel.
3. Normalize external document types at the LangChain adapter boundary and stop propagating dual
   document types through business code.
4. Remove explicit `Any` from configuration, contracts, and kernel without hiding it behind casts,
   dynamic attribute access, or ignored type errors.
5. Remove pure forwarding modules and policy-free forwarding functions in the wave scope.
6. Preserve active configuration semantics, supported package-level exports, build-job behavior,
   and kernel value semantics while retiring explicitly deprecated compatibility surfaces.
7. Install semantic ratchets that make every remaining protocol and short module reviewable.

## Non-Goals

- Do not clean unrelated protocols or forwarding functions in higher-level packages during this
  wave unless they consume a boundary being retired here.
- Do not merge unrelated kernel concepts solely to make a line-count metric reach zero.
- Do not add production dependencies or edit generated requirements lock files.
- Do not change HTTP routes, answer generation policy, retrieval ranking, graph algorithms, or
  build-job state transitions.
- Do not preserve an exact retired module, DTO field, or environment alias through a shim.

## Repository-Wide Sequence

The approved convergence sequence is:

1. configuration, contracts, and kernel;
2. application, app composition, and runtime;
3. query understanding, routing, retrieval, generation, and graph;
4. build pipeline, infrastructure, and API;
5. a whole-repository residual audit and final ratchet reset.

The categories are handled together inside each dependency cluster. A protocol deletion may make
a forwarding adapter unnecessary; merging that adapter may expose an `Any` that belongs to a DTO;
fixing all three in one wave avoids repeatedly migrating the same call graph.

## Ownership and File Layout

### Configuration

`rag_modules.configuration` converges from 38 Python modules to these eight:

- `__init__.py`: the supported package-level configuration surface;
- `assembly.py`: nested override merging and final model validation;
- `env.py`: environment source access, parsing, and override construction;
- `environment_schema.py`: the complete declarative environment-to-model field map;
- `loader.py`: the single public configuration loading pipeline;
- `models.py`: all Pydantic configuration section models and `GraphRAGConfig`;
- `profiles.py`: TOML profile discovery and loading; and
- `validation.py`: configuration diagnostics and parser/model error translation.

Delete the entire `model_sections/` package. Its classes move into `models.py`, which becomes the
only model owner rather than a re-export hub.

Delete the entire `env_specs/` package. Its declarations move into one
`environment_schema.py`; `env.py` imports that schema and remains responsible for reading and
parsing values. The new split is by responsibility (declaration versus execution), not by
configuration section.

Delete the entire `sections/` package. Its seven public loaders and shared loader are unused by the
production `load_config()` path and must not be replaced.

Move `ConfigErrorDetail` and `ConfigurationError` into `validation.py`, then delete `errors.py`.
The supported package-level imports from `rag_modules.configuration` continue to resolve directly
to those classes.

Delete `testing.py` from the production package. Test-only configuration construction moves under
`tests/`; operational scripts call the formal loader with explicit sources and overrides. Trivial
helpers that only invoke `QueryPlannerRuntimeSettings.from_config()` or
`QuerySemanticRuntimeSettings.from_config()` are replaced by those direct calls.

### Contracts

`rag_modules.contracts` remains the canonical cross-subsystem DTO package. Its package-level
surface is supported; intermediate module facades are not.

Delete `query.py` and `retrieval.py`, which only re-export owner modules. Repository callers import
from `rag_modules.contracts` when they intentionally use the package surface, or from the concrete
owner module when they need a narrow internal dependency.

Move the general coercion functions from `_common.py` and `query_utils.py` into
`rag_modules.kernel.json_types`, typed with `object`, `JsonValue`, or concrete collection types.
Delete both contract helper modules. This creates one low-level normalization owner instead of two
small, overlapping helper files.

Move evidence-specific LangChain conversions into `rag_modules.langchain_document_adapter` and
delete `contracts/langchain_compat.py`. The adapter remains the only production module allowed to
import `langchain_core.documents.Document` for document conversion.

Remove both `PageDocumentLike` protocols, from `contracts.retrieval_documents` and
`evidence_processing.models`. External documents are converted once at the adapter boundary;
internal retrieval, evidence, and generation code accepts `TextDocument` or `EvidenceDocument` as
appropriate, never `PageDocumentLike | EvidenceDocument`.

Remove `_CandidateSetView` from `contracts.runtime.retrieval`. Candidate-producing code passes the
explicit `Mapping[str, int]` statistics and degraded-detail sequence needed to construct
`HybridRetrievalOutcome`; the contract package no longer creates an object-shaped protocol for a
single call.

Delete `contracts/runtime/snapshot_utils.py`. `RouteSnapshot`, `GraphRetrievalSnapshot`, and
`GenerationSnapshot` each own typed copy/deserialize behavior. Internal callers pass a concrete
snapshot or `None`; mapping payloads are accepted only at serialization boundaries through the
corresponding `from_dict()` method.

Keep `BuildJobRepositoryPort` and `BuildJobRunnerPort`. They isolate multiple real implementations
and execution modes: file-backed persistence, in-process runners, and external-worker dispatch.
Keep `GraphQuery`, `PolicySnapshot`, and the build-job error module despite their size; each is a
stable, high-fanout contract with a distinct lifecycle or error responsibility.

### Kernel

Move vector artifact compatibility checks into `kernel/artifacts.py` and delete
`kernel/artifact_validation.py`; the functions depend only on `ArtifactManifest` and belong to the
same lifecycle.

Keep the following short kernel modules with explicit structural-ratchet entries:

- `documents.py`: the build/runtime-neutral `TextDocument` DTO;
- `retrieval.py`: the candidate degradation enum and validation;
- `semantic_schema.py`: versioned graph schema identifiers; and
- `time_parsing.py`: the shared duration parser used by domains and constraints.

`routing.py` remains the owner of routing values. `json_types.py` becomes the owner of JSON aliases,
safe JSON coercion, and primitive normalization used by the contract layer.

## Canonical Data Flows

Configuration has one path:

```text
environment / TOML profile / explicit overrides
    -> JSON-shaped nested overrides
    -> ordered merge and validation
    -> GraphRAGConfig
```

There is no section-specific loading path. Existing precedence remains defaults, query-policy
overlay, profile, environment, then explicit overrides. Each intermediate layer is validated with
the same source-kind and source-path information used today.

Documents have one external conversion boundary:

```text
LangChain Document
    -> rag_modules.langchain_document_adapter
    -> TextDocument or EvidenceDocument
    -> retrieval / evidence processing / generation
```

Internal functions no longer inspect arbitrary objects for `page_content` and `metadata`.

Retrieval outcomes receive explicit data:

```text
candidate source result
    -> documents + candidate_counts + degraded_candidates
    -> HybridRetrievalOutcome
```

Snapshot payloads deserialize at ingress and remain typed thereafter. Copying a snapshot returns a
detached instance of the same concrete type; no shared helper accepts arbitrary values.

## Hard Cutover and Compatibility Retirement

Every deleted exact module path must raise `ModuleNotFoundError`. No `sys.modules` alias, lazy
export, package `__getattr__`, import fallback, duplicate class, forwarding file, or deprecation
warning is permitted.

Remove the explicitly deprecated `EvidenceDocument` recipe-domain aliases:

- constructor parameters and properties `recipe_id` and `recipe_name`;
- property and constructor parameter `recipe_graph_evidence`;
- `_legacy_recipe_compat`; and
- conditional legacy recipe keys emitted by `to_dict()` and `to_metadata()`.

Repository callers migrate to `entity_id`, `entity_name`, and `domain_graph_evidence`. Domain-owned
API or evaluation models whose actual schema field is `recipe_name` are not renamed merely because
they contain the same word; only the deprecated aliases on `EvidenceDocument` are retired.

The canonical profile environment variables are:

- `GRAPH_RAG_PROFILE`;
- `GRAPH_RAG_PROFILE_PATH`; and
- `GRAPH_RAG_PROFILES_DIR`.

Retire `CONFIG_PROFILE`, `CONFIG_PROFILE_PATH`, `CONFIG_PROFILES_DIR`, and the undocumented
`GRAPH_RAG_API_TOKEN`. Provider credential variables `DASHSCOPE_API_KEY`, `OPENAI_API_KEY`, and
`MOONSHOT_API_KEY` remain distinct supported integration inputs documented by the model-provider
workflow, not compatibility aliases. `API_ACCESS_TOKEN` remains the sole API access-token variable.

## Type Policy

The wave ends with zero explicit `Any` name nodes in `configuration`, `contracts`, and `kernel`.

- Use `JsonObject`, `JsonValue`, and `JsonScalar` for intentionally open JSON values.
- Use `Mapping[str, object]` or `object` for unvalidated ingress.
- Convert stable known shapes to dataclasses or Pydantic models.
- Delete generic `copy_with(**changes: Any)` methods. Use explicit domain update methods or
  `dataclasses.replace()` inside the owning module.
- Do not replace `Any` with an unbounded `cast`, dynamic `getattr`, `# type: ignore`, or an
  equivalent escape hatch.
- Apply the existing strict mypy flags to all three packages through package-level overrides.

## Forwarding Definition and Policy

A policy-free forwarding function is a function whose executable body, after an optional
docstring, contains one call or awaited call and does not validate, normalize, select a strategy,
map an error, mutate owned state, or shape the result. Passing the same parameters to another
callable is delegation, not ownership.

The wave scope permits no such function merely to preserve an old name or intermediate object.
Callers move to the owner, or the call is inlined. Computed properties, DTO constructors, boundary
serializers, and functions that perform an actual normalization or policy decision are not
forwarders.

Pure import/`__all__` leaf modules are prohibited. Package initializers are governed separately by
the export policy: `rag_modules.configuration` and `rag_modules.contracts` remain documented
surfaces, while `rag_modules.kernel.__init__` may directly expose its intentionally small set of
foundational values. None may point through a retired module.

## Error Semantics

Configuration precedence, active environment parsing, profile validation, Pydantic validation,
and error path formatting remain behaviorally identical. Moving configuration error classes does
not change their inheritance, fields, or formatted message.

Retired Python paths, deprecated DTO fields, and retired profile environment aliases fail instead
of warning or falling back. Internal code that receives a raw mapping where a typed DTO is required
fails at that boundary; repository callers are migrated in the same change.

Build-job exception types, reducer transitions, persistence conflict handling, and API error
mapping remain unchanged. Kernel parsing and enum error behavior remain unchanged.

## Structural Ratchets

Extend `tests/test_abstraction_ratchets.py` and the existing type-contract tests so that:

1. the exact retained protocols in this wave are `BuildJobRepositoryPort` and
   `BuildJobRunnerPort`, each with its reviewed substitution rationale;
2. no explicit `Any` exists in configuration, contracts, or kernel;
3. only the reviewed short modules listed in this design remain in the wave scope;
4. retired module paths are absent and cannot be imported;
5. no production file imports a retired module or deprecated document alias;
6. no pure forwarding module or policy-free forwarding function remains in the wave scope;
7. package exports resolve directly to the canonical owner object; and
8. mypy package coverage cannot be weakened or replaced by redundant leaf entries.

The short-module ratchet records the responsibility, not just the path. A new or renamed short
module therefore requires an explicit design decision rather than an allowlist rename.

## Testing Strategy

Use test-driven changes for each independently reviewable slice:

1. Add failing retirement, protocol, short-module, forwarding, and no-`Any` structural tests.
2. Converge configuration models and environment schema; run configuration default, profile,
   environment, domain-pack, and validation tests.
3. Remove section loaders and production testing helpers; migrate tests and operational scripts.
4. Converge JSON/coercion ownership and contract facades; run contract, query, and serialization
   tests.
5. Normalize document boundaries, remove `PageDocumentLike` and recipe aliases, and run LangChain,
   evidence, retrieval, generation, evaluation, and API response tests.
6. Move snapshot behavior into DTO owners and run answer workflow, tracing, routing, graph, and SSE
   tests.
7. Remove `_CandidateSetView` and run hybrid retrieval and static type fixtures.
8. Merge artifact validation and run build, serving preparation, vector reuse, and kernel tests.
9. Run import DAG, public-surface, entrypoint, strict mypy, Ruff, full pytest, and release gates.

Required broad verification commands are:

```powershell
python -m mypy --config-file pyproject.toml
python -m ruff check rag_modules scripts tests
python -m ruff format --check rag_modules scripts tests
python -m pytest -q
python scripts/release_gate.py
git diff --check
```

The implementation may use narrower pytest slices first, but none of the broad gates above may be
omitted from a successful completion claim.

## Quantitative Acceptance Criteria

The baseline is measured on the current `development` HEAD with AST parsing over every
`rag_modules/**/*.py` file, excluding generated `__pycache__` content:

- 417 production Python files;
- 155 `Protocol` declarations;
- 95 non-`__init__.py` modules below 60 physical lines; and
- 367 `ast.Name(id="Any")` nodes.

This wave is complete only when:

- production Python files are at most 380;
- protocol declarations are at most 152;
- sub-60-line non-package modules are at most 64;
- `Any` name nodes are at most 209 globally and exactly zero in configuration, contracts, and
  kernel;
- configuration contains exactly the eight modules listed in this design;
- the wave scope contains no pure forwarding module or policy-free forwarding function;
- every retired import and deprecated `EvidenceDocument` alias is absent;
- configuration, contract, kernel, downstream migration, import-DAG, public-surface, and type
  tests pass;
- full Ruff, mypy, pytest, the offline release gate, and diff checks pass; and
- the final report includes before/after metrics and the retained protocol/short-module rationale.

These are maximums, not targets to game. If implementation safely removes more ceremony, the
ratchets use the lower measured result. A regression may not be accepted merely because it remains
below an older ceiling.

## Documentation

Update the architecture and public-surface retirement documentation in the implementation wave to
record canonical configuration ownership, retired module paths, the document normalization
boundary, and the two retained build-job ports. Historical approved specs and plans remain
unchanged.

## Follow-Up Boundary

After this wave passes all gates, measure the new repository baseline and start the application,
app-composition, and runtime convergence design. That wave must consume the lower ratchets from
this wave and may not recreate a deleted configuration, contract, or kernel abstraction.

## Implementation Evidence

Implementation commits:

- `7a1eb7ee` `refactor: converge configuration declarations`
- `f6a71fab` `refactor: retire parallel configuration surfaces`
- `2e356ffa` `refactor: converge typed kernel primitives`
- `d4696a51` `refactor: converge contract ownership and types`
- `00d13bb3` `refactor: normalize document boundaries`
- `2e857fbd` `fix: complete document compatibility retirement`
- `df3323af` `refactor: move runtime normalization to DTO owners`
- `1dd05c87` `test: ratchet foundational abstraction convergence`

The approved pre-wave baseline was 417 production Python files, 155 Protocol declarations,
95 non-`__init__.py` modules below 60 physical lines, and 367 `ast.Name(id="Any")` nodes.
The final AST measurement on 2026-07-24 is 379 production Python files, 152 Protocol
declarations, 64 non-`__init__.py` modules below 60 lines, and 174 `Any` name nodes. The
configuration package contains exactly eight Python modules, and configuration, contracts, and
kernel together contain zero `Any` name nodes. The fresh measurements equal every current
ratchet ceiling, so no ceiling was changed and no headroom remains.

The retained foundation Protocol declarations are deliberately limited to:

- `BuildJobRepositoryPort`: isolates the file-backed persistence implementation from callers
  and permits the distinct persistence execution modes.
- `BuildJobRunnerPort`: isolates in-process runners from external-worker dispatch while keeping
  the build-job execution boundary substitutable.

The reviewed sub-60-line foundation modules remain responsibility-owned rather than forwarding
leaves:

- `rag_modules/contracts/build_jobs/errors.py` — build-job domain errors.
- `rag_modules/contracts/graph.py` — graph-query DTOs.
- `rag_modules/contracts/runtime/policy.py` — runtime-policy DTOs.
- `rag_modules/kernel/documents.py` — document-normalization primitives.
- `rag_modules/kernel/retrieval.py` — retrieval-strategy primitives.
- `rag_modules/kernel/semantic_schema.py` — semantic-schema identifiers.
- `rag_modules/kernel/time_parsing.py` — timestamp-parsing primitives.

Fresh verification record:

| Command | Result |
| --- | --- |
| `python -m pytest tests/test_abstraction_ratchets.py -q` | 10 passed in 5.88s |
| `python -m pytest tests/test_type_contract_ratchets.py -q` | 10 passed in 0.50s |
| Final AST inventory over `rag_modules/**/*.py` | 379 files; 152 Protocols; 64 sub-60 modules; 174 `Any`; 8 configuration modules; 0 foundation `Any` |
| `python -m pytest tests/test_api_answer.py tests/test_api_build.py tests/test_api_public_surface.py tests/test_api_security.py tests/test_api_sse.py tests/test_entrypoints.py -q` | 104 passed in 29.93s |
| `python -m mypy --config-file pyproject.toml` | Success: no issues found in 384 source files (48.2s) |
| `python -m ruff check rag_modules scripts tests` | All checks passed (19.8s) |
| `python -m ruff format --check rag_modules scripts tests` | 630 files already formatted (2.2s) |
| `python -m pytest -q` | 2238 passed, 237 subtests passed in 760.68s |
| `python scripts/release_gate.py` | PASS: 69/69 cases, pass rate 1.0000, 9 route categories (6.2s) |
| `git diff --check` | Exit 0; no whitespace errors |
| `PRE_COMMIT_HOME=.pre-commit-task-8-cache pre-commit run --all-files` | Ruff check, Ruff format, and mypy hooks passed (9.2s) |

The initial `pre-commit run --all-files` attempt could not write the user-level pre-commit SQLite
cache. Re-running the identical hooks with a worktree-local cache passed; the temporary cache was
removed before committing.

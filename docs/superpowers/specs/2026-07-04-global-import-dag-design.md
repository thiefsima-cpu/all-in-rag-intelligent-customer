# Global Layered Import DAG Design

## Goal

Turn `rag_modules` into a genuinely directed, acyclic package graph. The migration removes
reverse dependencies instead of hiding them behind re-export modules, moves shared data types to
an implementation-independent kernel, assigns ports to their consumers, and installs an
executable allow-list that prevents both cycles and wrongly directed new imports.

The acceptance criterion is repository-wide: every production import under `rag_modules/` must
belong to the declared graph, and the graph must contain no strongly connected component with
more than one architectural node.

## Non-goals

- Preserve old Python import paths through aliases, forwarding modules, or deprecation shims.
- Change HTTP response schemas, retrieval ranking behavior, prompt behavior, or artifact formats.
- Add a dependency-injection framework or a third-party architecture checker.
- Start live Neo4j, Milvus, or DashScope services for the architecture test.

## Current Failure Mode

An AST inventory on 2026-07-04 finds one top-level strongly connected component containing 18
packages, including `contracts`, `configuration`, `query_understanding`, `retrieval`, `graph`,
`routing`, `runtime`, `build_pipeline`, and `infra`. Representative causes are:

- `contracts.query_settings` imports query-policy implementations to obtain defaults.
- configuration imports `CandidateSourceDegradationStrategy` from retrieval implementation code.
- `runtime.artifact_ports` imports a result DTO owned by `build_pipeline`.
- root `runtime_contracts.py` imports feature DTOs while feature packages import its ports.
- `app.runtime_contracts` only re-exports the root contract aggregate, creating a second ownership
  path rather than a boundary.
- Milvus imports and constructs the concrete root DashScope embedding client.
- routing imports concrete retrieval/graph-facing aggregate ports instead of owning its required
  collaborator shapes.

Existing public-surface tests prevent retired facades from returning, but do not reject a new
cycle or a new reverse edge between otherwise canonical packages.

## Architectural Decision

Use a layered DAG with an explicit per-node allow-list. Layers explain intent; the allow-list is
the machine-enforced source of truth. A dependency may point only from a higher layer to a lower
layer, and only when the exact edge is listed.

```text
interfaces
    |
    v
app composition
    |
    +-------> infra adapters/providers
    |              |
    v              v
runtime/build/routing orchestration
    |
    v
query-understanding/retrieval/graph/generation feature engines
    |
    v
configuration/query-policy/domain support
    |
    v
contracts
    |
    v
kernel
```

An arrow means "may import". Assembly remains the only place allowed to select concrete provider
implementations and connect them to consumer-owned ports.

## Architectural Nodes and Responsibilities

### Kernel

Create `rag_modules/kernel/` as the home of cross-package data with no feature behavior. It may
import only the standard library and Pydantic's JSON value type where necessary.

Initial kernel modules are:

- `kernel/json_types.py`: JSON aliases and coercion helpers currently under runtime.
- `kernel/documents.py`: the canonical text-document value type.
- `kernel/artifacts.py`: artifact stage, manifest, document artifact result, signatures, and
  aggregate statistics DTOs.
- `kernel/routing.py`: routing strategy and routing-statistics DTOs.
- `kernel/retrieval.py`: `CandidateSourceDegradationStrategy` and other genuinely shared retrieval
  enums, without normalization policy.

Kernel modules must not load environment variables, profiles, policy resources, provider SDKs,
or feature services. DTO methods may validate, normalize, serialize, and evolve their own data;
they may not invoke application policy.

The old DTO definitions are deleted after all callers move. Their former packages do not re-export
the kernel definitions.

### Contracts and domain support

`rag_modules/contracts/` remains the request/response contract layer and may depend on kernel
only. It must not import `query_policy`, configuration, runtime, or feature packages.

`QueryPlannerRuntimeSettings` and `QuerySemanticRuntimeSettings` become explicit resolved-value
contracts. Their defaults no longer instantiate query-policy model classes at import time. Calls
that need runtime settings receive fully resolved values from configuration assembly.

Pure parsing and domain helpers may depend on kernel/contracts. A domain module that invokes
query-understanding behavior is split: the data/parser stays in domain support and the behavioral
extractor moves to query understanding. This removes the present `domain -> query_understanding`
back edge.

### Policy and configuration

Query policy owns versioned policy resources and parsing. Configuration assembly owns default
selection and precedence.

The resolution flow is:

1. Read the policy selector and profile identity.
2. Load the selected query-policy bundle.
3. Convert policy runtime defaults into a plain configuration overlay.
4. Merge in this order: schema baseline, policy overlay, profile/TOML values, environment values,
   and explicit caller overrides.
5. Validate the merged payload into concrete configuration models.
6. Construct contract/runtime settings from that validated configuration.

No contract imports a policy model. No feature module independently creates a policy-default model
as a fallback. Missing or invalid selected policy data fails during configuration assembly with the
existing configuration error family, before runtime providers are built.

`RetrievalSettings` validates `CandidateSourceDegradationStrategy` from kernel. Retrieval runtime
profiles consume the already resolved configuration value; they do not read policy defaults.

### Consumer-owned ports

Delete both `rag_modules/runtime_contracts.py` and `rag_modules/app/runtime_contracts.py`. Replace
the aggregate with narrow protocols beside the code that consumes them:

- `query_understanding/ports.py`: completion behavior required by planning.
- `generation/ports.py`: completion and streaming behavior required by generation.
- `retrieval/ports.py`: reranking, candidate-source, vector-search, and graph-session behavior
  required by retrieval.
- `graph/ports.py`: graph driver/manager behavior required by graph execution.
- `routing/ports.py`: query-understanding, hybrid-retrieval, and graph-retrieval behavior required
  by routing.
- `build_pipeline/ports.py`: graph-data, artifact-cache, and vector-index behavior required by the
  build workflow.
- `runtime/ports.py`: manifest/statistics/lifecycle behavior required by runtime services.
- `app/ports.py`: tracing, shutdown, and provider surfaces consumed by application orchestration.
- `infra/milvus/ports.py`: `EmbeddingClientPort`, owned by the Milvus consumer.

Protocols expose only operations used by that consumer. A concrete object may satisfy several
structural protocols without importing or inheriting from all of them. Shared provider wire
response shapes stay private to the relevant consumer port module unless they are real kernel
DTOs.

`TYPE_CHECKING` imports are architecture dependencies too. They must follow the same allow-list;
forward references are not an exemption from the DAG.

### Feature engines and orchestrators

Feature packages exchange kernel/contracts DTOs and call collaborators through consumer-owned
ports. In particular:

- routing does not import concrete retrieval, graph, or query-understanding implementations;
- retrieval does not instantiate DashScope or other providers;
- graph does not import build-pipeline implementations;
- runtime does not import build-pipeline-owned DTOs;
- build pipeline does not import concrete infrastructure adapters;
- application composition is responsible for connecting concrete instances.

Root feature helpers that create extra architectural nodes are moved into their owning package
when encountered during cycle removal. Examples include fusion and parent-document behavior under
retrieval, answer-evidence behavior under generation/evidence processing, and entity-linking
behavior under graph/query understanding. Old root modules are deleted rather than forwarded.

### Infrastructure providers

Move all DashScope code to:

```text
rag_modules/infra/providers/dashscope/
    __init__.py
    embedding.py
    rerank.py
    http.py
```

The provider package owns HTTP request construction, response parsing, pooled sessions, circuit
breaker invocation, timeout propagation, and close behavior. The root `dashscope_clients.py` file
is deleted.

Milvus receives a required `EmbeddingClientPort` in its constructor. It neither imports DashScope
nor creates a fallback embedding client. Provider construction moves to app composition:

1. build the DashScope embedding adapter from resolved configuration;
2. pass it to the Milvus adapter as `EmbeddingClientPort`;
3. retain lifecycle ownership in the assembled runtime so each resource is closed once.

Retrieval reranking follows the same rule: app composition constructs the DashScope reranker and
injects it through `retrieval.ports.RerankClientPort`.

## Import DAG Policy

Add `tests/import_dag_policy.py` containing immutable architectural node definitions and the exact
set of allowed directed edges. Add `tests/test_import_dag.py` as the enforcement test.

The test performs these checks without importing production modules:

1. Parse every `rag_modules/**/*.py` file with `ast`.
2. Resolve absolute and relative imports to canonical module names.
3. Assign every production module to exactly one declared architectural node.
4. Fail on unclassified modules, so new packages cannot bypass governance.
5. Include imports nested under functions, methods, and `TYPE_CHECKING` blocks.
6. Reject every inter-node edge absent from the allow-list.
7. Run a strongly connected component algorithm and fail on multi-node components.
8. Reject self-dependency through a retired alternate ownership path where the policy lists that
   path as forbidden.
9. Detect literal `importlib.import_module()` calls and classify their target like normal imports;
   reject non-literal dynamic production imports unless the policy explicitly records them.

The failure message prints `source file:line`, resolved source/target nodes, and whether the failure
is an unclassified module, forbidden edge, or cycle. For a cycle it also prints one concrete edge
path, making the test useful during refactoring rather than merely acting as a gate.

The allow-list is not a baseline snapshot of current debt. It is introduced with the final target
edges only. Adding an edge requires an intentional policy edit and must still preserve acyclicity.

## Migration and Compatibility Policy

This is a hard cutover inside one release:

- update all production code, scripts, tests, type-check fixtures, and documentation to canonical
  imports;
- delete old modules and old package exports in the same change;
- update the public-surface retirement manifest/tests to assert that deleted paths stay absent;
- do not use `__getattr__`, `sys.modules`, import aliases, forwarding classes, or duplicate DTOs;
- do not retain optional fallback construction that recreates the old provider dependency.

Behavioral serialization compatibility is preserved where it is an external contract. Python
module-path compatibility is intentionally not preserved.

## Error Handling and Lifecycle

- Invalid degradation strategy values fail in configuration validation and list the supported
  kernel enum values.
- Missing policy defaults fail during configuration assembly, not later in contracts or feature
  execution.
- Missing required embedding/rerank providers fail during application assembly with a focused
  provider-construction error.
- DashScope request, cancellation, timeout, response-count, and response-shape behavior remains
  unchanged after relocation.
- App composition records ownership of injected closeable providers. Milvus closes only resources
  it owns; it must not close an independently owned injected embedding provider twice.

## Testing Strategy

Implementation follows test-first migration slices:

1. Add failing kernel-ownership and no-policy-import tests.
2. Move shared enums/DTOs and make the focused tests pass.
3. Add failing configuration-default-injection tests, then remove contract/policy coupling.
4. Add consumer-port tests and migrate one consumer family at a time.
5. Add failing provider-isolation tests, then move DashScope and require Milvus injection.
6. Add the final import allow-list and cycle test, then remove remaining reverse edges until the
   entire production graph passes.
7. Run targeted contract, configuration, retrieval, routing, artifact, provider, assembly, API,
   public-surface, and type-contract tests.
8. Run Ruff, mypy, the full pytest suite, and `python scripts/release_gate.py` before completion.

No test requires external network access. Provider tests use injected sessions and deterministic
responses; architecture tests operate on source files only.

## Documentation Impact

Update `docs/public_surface_retirement_plan.md` to remove `app.runtime_contracts` from canonical
facades and record the deleted root provider/contract paths. Update the main architecture or
developer documentation with the layer diagram, port ownership rule, default-resolution flow, and
the command for the import DAG test.

## Acceptance Criteria

- The AST-derived graph for every module under `rag_modules/` has no cycle.
- Every inter-node import is present in the reviewed allow-list.
- Kernel and contracts import no feature, configuration, policy, runtime, app, interface, or infra
  implementation.
- Contracts obtain no defaults from query-policy implementations.
- Runtime settings receive resolved values from configuration assembly.
- Shared routing/artifact DTOs have a single kernel definition.
- Aggregate `runtime_contracts.py` modules no longer exist.
- DashScope exists only under `infra/providers/dashscope`.
- Milvus depends only on its local `EmbeddingClientPort` for embeddings and has no concrete-provider
  fallback.
- Old imports fail rather than forward.
- Focused tests, full pytest, Ruff, mypy, and the offline release gate pass.

# Semantic Import DAG Hardening Design

## Goal

Remove the shortest semantic dependency cycle in `rag_modules` and upgrade the import-DAG gate so
type-only imports are governed by the same architectural policy as runtime imports.

The completed graph must satisfy all of these conditions:

- the runtime import graph is acyclic;
- the complete semantic graph, containing runtime and `TYPE_CHECKING` imports, is acyclic;
- every production module belongs to exactly one declared architectural node;
- every inter-node dependency is present in the reviewed allow-list;
- runtime owns only the minimal collaborator shapes it consumes and does not type-depend on
  routing or build-pipeline implementations;
- graph-preparation DTOs have one implementation-independent owner.

## Current Failure

`tests/test_import_dag.py` deliberately skips the body of `if TYPE_CHECKING:` blocks. The runtime
graph therefore passes even though the type graph contains this strongly connected component:

```text
build_pipeline -> runtime -> routing -> retrieval -> build_pipeline
```

The reverse edges are type-only:

- `runtime -> build_pipeline` through `GraphLoadCounts` and `GraphPreparationStats`;
- `runtime -> routing` through `RoutingWorkflowProtocol` in runtime statistics access;
- `retrieval -> build_pipeline` through `GraphLoadCounts`, `GraphNode`, and
  `GraphPreparationStats`.

`app.ports` also imports the build-owned DTOs under `TYPE_CHECKING`. That edge does not create the
shortest cycle because app is a higher-level assembler, but the DTO ownership is still wrong.

The repository already documents that `TYPE_CHECKING` imports are architecture dependencies and
that the DAG gate must classify every module and enforce an allow-list. The current test is a
reduced implementation that omits those checks.

## Decisions

### Hard cutover

This migration does not preserve old build-pipeline DTO paths. There are no aliases, forwarding
definitions, package re-exports, or deprecation shims in the former owner.

These old paths must stop resolving:

- `rag_modules.build_pipeline.GraphNode`;
- `rag_modules.build_pipeline.graph_preparation.GraphNode`;
- `rag_modules.build_pipeline.graph_preparation.models.GraphNode`;
- `rag_modules.build_pipeline.graph_preparation.models.GraphLoadCounts`;
- `rag_modules.build_pipeline.graph_preparation.statistics.GraphPreparationStats`.

### Neutral DTO owner

Create `rag_modules/contracts/graph_preparation.py` as the single definition site for:

- `GraphNode`;
- `GraphLoadCounts`;
- `GraphPreparationStats`.

These values cross build, retrieval, app, and diagnostics boundaries. They describe exchanged
data and stable serialization rather than build behavior or recipe-domain policy, so contracts is
a better owner than `domain.shared`.

`rag_modules.contracts` exports these names as its canonical owner-package surface. Former build
packages must not export them.

`rag_modules/build_pipeline/graph_preparation/models.py` retains only build-private data:

- `GraphRelation`;
- `PreparedIngredientInput`;
- `PreparedStepInput`.

`rag_modules/build_pipeline/graph_preparation/statistics.py` retains the statistics calculation
service and imports its result DTO from contracts.

### Consumer-owned runtime statistics ports

Runtime statistics access must describe the minimum shapes needed for coercion. It must not import
the complete routing workflow or build-pipeline DTOs.

`runtime.stats_ports` owns narrow structural protocols for sources that expose only:

- `get_statistics()` for graph preparation statistics;
- `get_collection_stats()` for vector collection statistics;
- `get_route_statistics()` for routing statistics;
- `stats()` for query tracing statistics;
- `to_dict()` for retrieval runtime-profile payloads.

`RuntimeStatsAccessPort` accepts these local protocols. `DefaultRuntimeStatsAccess` imports only
the local runtime ports and converts their results with `coerce_json_object`.

`runtime.ports.GraphDataModulePort` continues to describe graph-data behavior needed by runtime
artifact operations, but `load_graph_data()` and `get_statistics()` return an opaque `object` from
runtime's perspective. Runtime does not inspect the concrete DTO; the existing JSON coercion is
the boundary.

Build, retrieval, and app ports may use the canonical contracts DTOs because contracts is below
those consumers in the dependency graph.

## Alternatives Considered

### Put the DTOs in `domain.shared`

This would remove the cycle, but graph load counts and preparation diagnostics are not recipe
domain concepts. It would mix infrastructure-facing statistics into the domain layer.

### Give every consumer a local structural shape

This would minimize imports but duplicate actual transfer objects and weaken the single-source
serialization contract. Local protocols are appropriate for runtime behavior, not for DTOs that
are constructed and passed across subsystems.

### Keep build ownership and add compatibility forwarding

This preserves import paths but keeps the semantic ownership reversal visible to the type graph.
It conflicts with the repository's hard-cutover policy and is rejected.

## DAG Policy and Collection

Create `tests/import_dag_policy.py` to hold policy data independently from AST traversal:

- architectural node names;
- canonical module prefixes, including root-level singleton modules;
- the exact reviewed set of allowed directed inter-node edges;
- the controlled lazy-loading files whose target tables must be inspected:
  `rag_modules/__init__.py`, `graph/__init__.py`, `infra/__init__.py`,
  `query_understanding/__init__.py`, `retrieval/__init__.py`, and `routing/__init__.py`.

Every `rag_modules/**/*.py` file must resolve to exactly one architectural node. Longest-prefix
matching permits specific singleton modules alongside package prefixes. No match is an
unclassified-module violation; multiple equally specific owners are an ambiguous-classification
violation.

The AST collector records each internal import as an edge containing:

- source module and architectural node;
- target module and architectural node;
- source file and line number;
- dependency kind: `runtime` or `type`.

Normal imports, including imports inside functions and methods, are runtime dependencies. Imports
inside the body of `if TYPE_CHECKING:` or `if typing.TYPE_CHECKING:` are type dependencies. An
`else` branch remains runtime code. Nested guards preserve the type context for their descendants.

Absolute and relative imports resolve to canonical module names before classification. Controlled
lazy-load module targets are classified like static imports so dynamic loading cannot silently
bypass the policy. Unsupported non-literal production imports fail unless the policy explicitly
identifies the controlled loader and its complete target table is statically discoverable.

## Graph Checks

The gate builds two graphs from the same edge inventory:

1. the runtime graph contains only `runtime` edges;
2. the semantic graph contains both `runtime` and `type` edges.

Both graphs run through the strongly connected component check. The semantic graph is the final
architecture invariant; the separate runtime graph preserves operational visibility and produces
more precise diagnostics.

Every inter-node edge, regardless of dependency kind, must be listed in the same allow-list. The
allow-list expresses permitted architecture, not a snapshot of current debt. A new allowed edge
requires an intentional policy change and must leave both graphs acyclic.

Failures report actionable evidence:

- unclassified or ambiguously classified module names;
- unsupported dynamic imports;
- forbidden edge source file and line, dependency kind, source node, and target node;
- graph kind and a concrete path for every detected cycle.

## Data Flow After Migration

Graph preparation loads Neo4j records and constructs contract-owned `GraphNode` and
`GraphLoadCounts` values. Its statistics service constructs the contract-owned
`GraphPreparationStats`. Build, retrieval, and app consumers annotate those values through the
neutral contract owner.

Runtime artifact and statistics services receive objects through consumer-owned protocols. They
coerce values through `to_dict()` or mapping behavior and expose JSON objects. Runtime never
imports the build or routing packages to understand those values.

No HTTP schema, artifact format, graph query, retrieval ranking, or serialization field changes.

## Test-First Migration

Implementation follows red-green-refactor slices:

1. Add focused collector tests that prove `TYPE_CHECKING` bodies become type edges and their
   `else` branches remain runtime edges.
2. Add policy tests for unclassified modules, ambiguous classifications, forbidden edges, and
   dependency-kind diagnostics.
3. Run the repository DAG test and observe the current semantic SCC while the runtime graph
   remains acyclic.
4. Add contract-ownership tests for the canonical DTO modules and the removal of former package
   exports.
5. Move the DTO definitions and update production imports, tests, and typecheck fixtures.
6. Add runtime statistics protocol tests, then replace routing/build annotations with local
   consumer-owned protocols or opaque results.
7. Run the upgraded gate until both graphs contain no cycle and every edge is allowed.

Focused verification covers:

- `tests/test_import_dag.py`;
- graph-preparation loader, module, document, and statistics tests;
- consumer-owned port and runtime type-contract tests;
- runtime artifact/statistics adapters;
- build statistics presenter and knowledge-base workflow tests;
- document artifact cache tests;
- public-surface and type-contract ratchets;
- mypy type-contract fixtures.

Completion verification runs the full pytest suite, repository pre-commit hooks, and
`python scripts/release_gate.py`. No test requires live Neo4j, Milvus, provider credentials, or
network access.

## Documentation Impact

This design records the hard-cutover paths and the concrete runtime/type graph behavior. The
existing global import-DAG design already specifies the layered architecture, module
classification, dynamic-import governance, and allow-list principle; this change restores that
intended enforcement rather than changing the architecture.

## Acceptance Criteria

- `GraphNode`, `GraphLoadCounts`, and `GraphPreparationStats` have one definition under contracts.
- Former build-pipeline DTO imports and exports fail rather than forward.
- Runtime has no runtime or type dependency on build_pipeline or routing.
- Retrieval has no runtime or type dependency on build_pipeline.
- The runtime import graph is acyclic.
- The complete runtime-plus-type import graph is acyclic.
- Every production Python module is classified exactly once.
- Every inter-node dependency is present in the reviewed allow-list.
- Failure output identifies file, line, dependency kind, nodes, and concrete cycle path.
- Focused tests, full pytest, pre-commit, mypy coverage, and the offline release gate pass.

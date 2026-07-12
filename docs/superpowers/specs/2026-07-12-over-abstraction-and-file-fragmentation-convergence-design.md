# Over-Abstraction and File-Fragmentation Convergence Design

Status: approved in conversation; pending written-spec review

## Context

The repository's subsystem boundaries are valuable, but recent architecture work has also
accumulated interface ceremony that no longer protects a meaningful substitution boundary. At the
start of this design, the main package contains 429 Python files, 161 files below 60 lines, and 157
top-level `Protocol` declarations. Line count alone is not a defect, but the current tree includes
clear examples of fragmentation:

- eight `rag_modules.app.services` leaf modules that only re-export implementations now owned by
  `rag_modules.application`;
- `rag_modules.runtime.snapshot_utils`, which only forwards to the contract kernel;
- `rag_modules.app.contracts`, which only re-exports contracts from their canonical owners;
- four bootstrap invocation protocols with one matching adapter implementation each; and
- a 91-entry mypy override whose contiguous strict packages and isolated strict modules are mixed
  into one manually maintained list.

The compatibility files also conflict with the repository's existing public-surface policy, which
states that active Python compatibility layers are retired and old imports should fail instead of
forwarding.

## Goals

1. Make `rag_modules.application` the only canonical owner of answer and knowledge-base use cases.
2. Remove forwarding modules that preserve no supported compatibility contract.
3. Remove internal protocols and adapters that merely restate one concrete collaborator call.
4. Preserve consumer-owned ports that enforce a real cross-subsystem dependency direction or are
   used for supported substitution.
5. Replace redundant per-module mypy configuration with package rules wherever the current strict
   coverage is contiguous.
6. Add semantic structural tests that prevent the same ceremony from returning.
7. Preserve API behavior, runtime behavior, build behavior, and the established import DAG.

## Non-Goals

- Do not perform a repository-wide rewrite of all small files or all protocols.
- Do not merge cohesive collaborators merely because they are below an arbitrary line threshold.
- Do not remove provider protocols that are actively replaced by tests or callers during
  composition.
- Do not make all of `rag_modules.app`, `rag_modules.retrieval`, or `rag_modules.graph` strict in
  this slice.
- Do not add a deprecation period, forwarding alias, lazy compatibility export, or fallback import
  for the retired module paths.
- Do not change HTTP routes, schemas, answer semantics, build semantics, or runtime lifecycle
  behavior.

## Boundary Rules

`rag_modules.application` owns pure application use cases, their DTOs, and consumer-owned ports.
`rag_modules.app` owns runtime composition, provider selection, lifecycle coordination, and system
facades. A use case may consume a port but may not import a concrete retrieval, generation,
query-policy, build-pipeline, configuration, or app-composition implementation.

A `Protocol` remains justified when at least one of these conditions holds:

- it reverses a dependency across subsystem boundaries;
- it has multiple production implementations;
- it is an intentional public extension point; or
- tests or supported callers replace it to isolate an expensive or external dependency.

"One protocol + one same-boundary adapter + dynamic forwarding" is not a boundary. A concrete
collaborator should be called directly in that case. Likewise, a small file is merged only when it
is a pure forwarder, a pure re-export, or a single declaration with no independent ownership or
lifecycle.

Provider protocols remain in this slice because runtime composition and tests inject alternate
provider implementations. Application ports remain because they separate use cases from concrete
subsystems. `AnswerWorkflowCopy` remains a port, but it moves into the application port module
instead of occupying a dedicated file.

## Canonical Modules and Deletions

Delete these compatibility or aggregation modules:

- `rag_modules/app/services/answer_copy.py`
- `rag_modules/app/services/answer_models.py`
- `rag_modules/app/services/answer_pipeline.py`
- `rag_modules/app/services/answer_result_factory.py`
- `rag_modules/app/services/answer_trace_assembler.py`
- `rag_modules/app/services/answer_workflow.py`
- `rag_modules/app/services/knowledge_base_service.py`
- `rag_modules/app/services/trace_adapters.py`
- `rag_modules/runtime/snapshot_utils.py`
- `rag_modules/app/contracts.py`
- `rag_modules/app/bootstrap_facade_contracts.py`
- `rag_modules/app/bootstrap_facade_support.py`

The resulting ownership is:

- answer use cases and DTOs: `rag_modules.application.answering`;
- knowledge-base use case: `rag_modules.application.knowledge_base`;
- application-owned ports, including `AnswerWorkflowCopy`:
  `rag_modules.application.ports`;
- snapshot cloning helpers: `rag_modules.contracts.runtime.snapshot_utils`;
- composition collaborator contracts: `rag_modules.app.composition.contracts`;
- provider contracts: `rag_modules.app.providers.contracts`; and
- diagnostics and shutdown behavior: real modules under `rag_modules.app.services`.

`rag_modules.app.services.__init__` remains, but it exports only
`RuntimeDiagnosticsService` and `RuntimeShutdownService`. It does not re-export application use
cases or DTOs. Root and package-level public exports that intentionally expose application types
must resolve directly to `rag_modules.application`, not through `rag_modules.app.services`.

Deleting the twelve modules above is expected to reduce the main-package file count by twelve.
The implementation must report the measured result rather than treating that estimate as proof.

## Bootstrap Simplification

Delete these protocols:

- `SystemRuntimeBootstrapServiceProtocol`
- `BuildBootstrapperInvocationProtocol`
- `ServingBootstrapperInvocationProtocol`
- `GraphBootstrapperInvocationProtocol`

Delete the corresponding `BuildBootstrapperInvocationAdapter`,
`ServingBootstrapperInvocationAdapter`, and `GraphBootstrapperInvocationAdapter`. These adapters
currently use dynamic `getattr` delegation and `cast` to call methods already declared by the real
composition collaborator contracts.

Move `_ComposedBootstrapperFacade` into `rag_modules.app.bootstrap`. Public bootstrapper classes
continue to compose and bind their collaborator dataclasses, then call the resolved collaborators
directly:

- build runtime: `BuildRuntimeFactoryProtocol.build`;
- build and rebuild: `BuildRuntimeExecutorProtocol.build_knowledge_base` and
  `rebuild_knowledge_base`;
- serving lifecycle: `ServingRuntimeLifecycleServiceProtocol.build_ready`, `prepare`, and
  `prepare_with_shared_runtime`; and
- system runtime: the concrete system runtime bootstrap service's `build` method.

The existing composition protocols above remain because they are injected at real collaborator
boundaries and are used by tests. Removing the invocation layer must not collapse build and serving
composition into the public facade.

## Import Migration and Compatibility Policy

Production code, scripts, tests, and documentation move to canonical imports in the same change.
The deleted paths receive no `sys.modules` alias, package attribute, module-level `__getattr__`,
lazy export, or forwarding file. Importing a retired path must raise `ModuleNotFoundError`.

Update `rag_modules.public_surface_manifest` so that:

- `rag_modules.application` remains the canonical application-use-case surface;
- `rag_modules.app.services` describes only its real app lifecycle services; and
- no entry describes the deleted modules as compatibility imports or canonical facades.

Update `docs/architecture.md`, `docs/app_composition_maintenance_guide.md`, and
`docs/public_surface_retirement_plan.md` to use the new canonical ownership and to record the hard
cutover. Historical plan documents are not rewritten; they remain records of the paths that existed
when those plans were executed.

## Mypy Strict-Island Normalization

Preserve the current strict-island semantics: `disallow_untyped_defs = true` and
`ignore_missing_imports = false`. Normalize the module selection without weakening or silently
expanding established coverage.

Use package-level rules for contiguous strict areas, including:

- `rag_modules.application` and `rag_modules.application.*`;
- `rag_modules.domain` and `rag_modules.domain.*`;
- `rag_modules.contracts` and `rag_modules.contracts.*`;
- `rag_modules.interfaces.api.*`;
- `rag_modules.app.providers` and `rag_modules.app.providers.*`;
- `rag_modules.app.services` and `rag_modules.app.services.*`;
- `rag_modules.generation.execution` and `rag_modules.generation.execution.*`;
- `rag_modules.kernel` and `rag_modules.kernel.*`;
- `rag_modules.runtime` and `rag_modules.runtime.*`;
- `rag_modules.query_policy.parsers` and `rag_modules.query_policy.parsers.*`; and
- `rag_modules.build_pipeline.graph_preparation` and
  `rag_modules.build_pipeline.graph_preparation.*`.

Remove child entries already covered by those patterns. Partially strict packages such as
`rag_modules.app.composition`, `rag_modules.retrieval`, `rag_modules.graph`,
`rag_modules.routing`, and `rag_modules.observability` retain a short, grouped leaf-module ratchet.

Do not replace the current list with `rag_modules.app.*` in this slice. A diagnostic strict run
expanded into 50 unfinished dependency files and reported 111 `no-untyped-def` errors. Closing that
separate type-annotation backlog would obscure the architecture cleanup.

Extend `tests/test_type_contract_ratchets.py` so the configuration is self-normalizing:

- a child module may not be listed under an existing wildcard;
- when every Python module in a subpackage is already covered, the configuration must use the
  package pattern instead of enumerating every child; and
- an existing strict target may not silently fall out of the expanded configured coverage.

A newly created module under a package-level strict rule is strict automatically. Leaf entries are
allowed only for packages that have not yet reached package-wide coverage.

## Structural Ratchets

Add focused AST-based checks for the current convergence boundary:

1. Under `rag_modules/app`, `rag_modules/application`, and `rag_modules/runtime`, a non-package
   module whose executable body consists only of imports, `__all__`, and a docstring is rejected
   unless it is an explicitly approved canonical facade. `rag_modules.app.diagnostics` is the
   current approved split-model facade. `__init__.py` files are package surfaces and are evaluated
   separately.
2. Every deleted module path remains absent and import attempts fail.
3. A production class named `*Adapter` may not explicitly inherit a `*Protocol`. Structural
   conformance does not require adapter inheritance.
4. New protocols in the current boundary belong in consumer-owned `ports.py`, explicit
   `contracts.py`, or an approved public extension surface. Existing exceptions are recorded as a
   non-growing ratchet with a short rationale.

These checks are intentionally semantic and scoped. The repository does not fail merely because a
cohesive implementation file has fewer than 60 lines, nor does it reward merging unrelated
responsibilities into a large file.

## Behavior and Error Handling

No runtime error-handling policy changes. The direct bootstrap calls use the same typed
collaborators and allow their existing exceptions to propagate through the same public boundaries.
No catch-all wrapper is added to emulate the removed invocation adapters.

The only intentional new failure is import failure for retired Python paths. If a production file,
script, ordinary test, or maintained document still uses one of those paths, migrate the caller.
Do not restore a compatibility layer.

## Test Strategy

Run the narrowest relevant tests first:

- application use cases and answer workflow;
- bootstrap facade and runtime composition tests;
- system runtime and runtime factory tests;
- consumer-owned-port and import-DAG tests;
- public manifest, retired-facade, and dependency-boundary tests;
- mypy strict-island ratchets; and
- API answer, SSE, build, and public-surface slices.

Then run:

1. Ruff check and format checks for touched files.
2. `python -m mypy --config-file pyproject.toml`.
3. Full Ruff check and format check.
4. `python -m pytest -q`.
5. `python scripts/release_gate.py`.
6. `git diff --check`.

If a package wildcard expands strict coverage unexpectedly, restore an equivalent minimal set of
leaf entries for that incomplete package and record it as a later convergence target. Do not remove
an existing strict module or relax strict flags to make the gate pass.

## Completion Criteria

The convergence is complete only when all of the following are true:

- the twelve retired modules are absent;
- old imports fail instead of forwarding;
- canonical imports point directly to application, composition, provider, or contract owners;
- the four bootstrap-only protocols and three invocation adapters are absent;
- bootstrap behavior tests pass with direct typed collaborator calls;
- mypy overrides use package patterns wherever current coverage is contiguous and contain no
  redundant child entries;
- structural tests reject regression to forwarding leaf modules and protocol-inheriting adapters;
- architecture, maintenance, and public-surface documentation agree with the code;
- focused tests, full mypy, full Ruff, full pytest, the offline release gate, and diff checks pass;
  and
- final reporting includes measured before/after Python-file, protocol, and forwarding-module
  counts, plus any remaining leaf strict-island entries.

## Follow-Up Scope

After this slice is stable, apply the same rules subsystem by subsystem. Prioritize partial strict
packages and clusters of forwarding modules, but require a separate focused design when cleanup
would change a public extension surface or cross-subsystem port. Do not reopen this change into an
all-repository abstraction rewrite.

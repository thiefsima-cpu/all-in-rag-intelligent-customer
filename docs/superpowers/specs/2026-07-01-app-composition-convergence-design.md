# App Composition Convergence Design

## Context

`rag_modules/app/composition/` and `rag_modules/app/provider_components/` now
hold a complete runtime assembly model, but the reading path is expensive for
new contributors. A common change requires jumping between public app facades,
provider facets, factories, lifecycle services, runtime state, and boundary
tests before it is clear where the behavior belongs.

The repository already has a strong compatibility-retirement policy: old
facades fail instead of forwarding, and canonical packages are preferred over
bridges. This refactor should follow that policy. It should converge internal
assembly boundaries instead of preserving thin forwarding classes as another
compatibility layer.

## Goals

- Add a maintainer guide that answers: "If I change this capability, which
  provider, lifecycle service, factory, or app service owns it?"
- Make `rag_modules.app.providers` the single provider-facing app boundary.
- Remove or inline provider classes that only forward to one constructor or one
  lower-level method.
- Collapse lifecycle services that only add an extra hop without owning a state
  rule.
- Update boundary and type tests so they protect the new converged structure,
  not the old intermediate wrappers.

## Non-Goals

- Changing serving API payloads, build API payloads, or route names.
- Changing retrieval, generation, query-understanding, graph, or build-pipeline
  business behavior.
- Preserving import compatibility for internal provider-component modules that
  are removed or renamed.
- Introducing a new `domain/` or `pipelines/` package layout.

## Architecture Decision

Use a smaller assembly surface with explicit ownership rules:

- `rag_modules.app.providers` owns provider protocols, default provider
  construction, and injectable provider groups.
- `rag_modules.app.composition` owns runtime factories, runtime state, and
  lifecycle orchestration that has real sequencing or readiness semantics.
- `rag_modules.app.services` owns application use cases such as answering,
  diagnostics, shutdown, and knowledge-base operations.
- Feature packages own feature behavior. Provider code may instantiate those
  services, but should not host feature policy.

`rag_modules.app.provider_components` should no longer be a package that callers
or tests navigate as the provider model. If some files remain during the
refactor, they are implementation files only and should not be the documented
maintenance entrypoint.

## Provider Boundary

The provider surface should group capabilities by the decisions contributors
actually make:

- Infrastructure: Neo4j, Milvus, artifact stores, tracing sinks, runtime
  artifact access, and query tracer construction.
- Build pipeline: document artifacts and semantic graph schema sync.
- Retrieval runtime: retrieval profile, query-understanding service,
  traditional retrieval, graph retrieval, and routing workflow construction.
- Generation: grounded generation workflow construction.
- Application services: knowledge-base service, answer workflow, runtime
  diagnostics, and shutdown service.

Thin providers that only call a single constructor should be inlined into the
owning provider group unless they express a meaningful injection seam. For
example, a provider method that only returns
`GenerationWorkflowService.from_config(config)` does not need its own provider
class. A provider group is justified when it prevents the runtime factories from
knowing concrete adapter construction details or when tests need to inject a
capability group.

`create_default_runtime_provider()` remains the public creation function. The
old internal class names are not compatibility commitments. Tests that currently
import `DefaultGenerationComponentProvider`,
`DefaultLifecycleComponentProvider`, or similar one-method classes should move
to the new provider boundary.

## Lifecycle Boundary

Lifecycle classes should exist only when they own a state transition, readiness
rule, or ordering constraint:

- Keep build lifecycle behavior where it coordinates build/rebuild execution and
  serving refresh after a successful build.
- Keep readiness behavior where it centralizes initialized/ready validation and
  user-facing errors.
- Keep initialization behavior where it decides whether to reuse, refresh, or
  build runtimes.
- Collapse a lifecycle helper if it only delegates to another lifecycle helper
  or preparer without adding a rule.

The target reading path should avoid chains such as
`manager -> refresh service -> serving lifecycle -> preparer` when the middle
service does not add policy. The manager may still delegate, but each delegate
must name a real state responsibility.

## Maintenance Guide

Add a guide under `docs/` and link it from `docs/architecture.md`. The guide
should include:

- A decision table mapping common changes to the owning file or package.
- A short provider-vs-lifecycle rule of thumb.
- A "do not add" section for thin wrappers, compatibility facades, ad hoc
  dictionaries, and feature behavior inside provider code.
- A testing map that points provider changes, lifecycle changes, runtime factory
  changes, and public workflow changes to focused tests.

The guide is part of the refactor, not a substitute for it. It should describe
the converged structure after code changes, not the old structure with more
explanation.

## Testing Strategy

Update tests in two layers:

- Behavioral tests keep proving that runtime assembly, build/serving lifecycle,
  provider injection, diagnostics, tracing, and answering still work.
- Boundary tests change from protecting the old split provider components to
  preventing reintroduction of thin wrappers and compatibility shells.

Focused checks should include:

- provider construction and injection tests for `rag_modules.app.providers`;
- runtime lifecycle tests for initialization, readiness, build/rebuild, refresh,
  and shutdown;
- serving runtime factory/preparer tests where provider grouping changes touch
  the runtime object graph;
- public-surface tests that keep `composition` and any remaining implementation
  provider modules internal-only;
- type-contract ratchets updated to the new provider protocol locations.

For release-sensitive completion, run `python scripts/release_gate.py` after
the focused test set passes.

## Acceptance Criteria

- A maintainer can answer "where do I change this app capability?" from the new
  guide without reading every composition file first.
- The default provider is constructed through `rag_modules.app.providers`.
- One-method or pure-forwarding provider classes are removed or inlined unless a
  testable injection reason remains.
- Lifecycle helpers that do not own state policy are removed or merged into the
  lifecycle class that owns the rule.
- Tests no longer import removed internal provider-component classes.
- Boundary tests fail if new compatibility facades or no-policy wrapper classes
  are introduced.
- Focused runtime/provider tests pass, and skipped broader checks are reported.

## Risks

This is an internal breaking refactor. Existing tests that import internal
provider-component classes must move with the code. That is intentional because
the package is already marked internal-only.

Over-collapsing can make factories too large. The implementation should merge
only no-policy wrappers and keep separate classes when they preserve an actual
state rule, adapter boundary, or testable capability group.

The public `rag_modules.app.providers` module is a registered public API
surface. It should remain the stable entrypoint, but it does not need to
re-export every internal provider class that existed before the convergence.

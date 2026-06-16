# Public Surface And Legacy Facade Closure Design

## Goal

Close the public-surface and legacy-facade cleanup decisively instead of
adding more compatibility patches. Internal code, scripts, and ordinary tests
should depend on canonical packages only. Legacy facades may remain only as
explicitly registered external compatibility bridges during the migration
window.

## Current Context

The repository already has the main pieces of this boundary:

- `rag_modules.public_surface_manifest` describes canonical public API,
  service API, internal-only packages, and remaining legacy facades.
- `docs/public_surface_retirement_plan.md` documents retired facades and the
  remaining migration window.
- Boundary tests block internal imports from repo-root config, removed compat
  packages, retired query/runtime facades, and root graph wrappers.
- `rag_modules.app.legacy_surface` centralizes flat `system.*` and
  `runtime.*` compatibility attributes.
- Public bootstrapper facades already delegate to composition and lifecycle
  services through invocation adapters.

The remaining work is to make these decisions harder to drift from: derive
test expectations from the manifest, keep wrapper modules visibly thin, and
document exactly why the remaining external compatibility bridges still exist.

## Recommended Approach

Use an aggressive closure strategy with a minimal external compatibility
bridge. The implementation should not delete every compatibility import at
once, because `config.py`, `rag_modules.graph_data_preparation`, and
`rag_modules.graph_indexing` are still documented as external migration
surfaces. Instead, it should make the rule strict: no repository-internal
consumer may rely on those modules, and each remaining facade must be a thin,
registered, tested bridge to a canonical module.

This gives the codebase a clean internal architecture while avoiding a surprise
break for external callers that still import the legacy module names.

## Public Surface Model

`rag_modules.public_surface_manifest` is the single source of truth for public
surface classification. Tests should use the manifest when checking expected
module sets rather than duplicating hard-coded lists in multiple files.

The model has four explicit categories:

- Public API: stable external entrypoints such as app, interface, and provider
  surfaces.
- Service API: repository-internal domain packages that are stable for
  cross-module use.
- Internal only: composition and provider-component packages used by assembly
  code, not by feature code.
- Legacy public surface: registered compatibility bridges that exist only for
  the external migration window.

The manifest should also describe retirement phase and canonical target for
each legacy bridge. If a new facade is added without manifest coverage, tests
should fail.

## Legacy Facade Rules

Legacy facades must stay deliberately boring:

- They re-export or delegate to one canonical target.
- They do not own business logic, state, lifecycle orchestration, or fallback
  policy.
- They do not import from retired compat namespaces.
- They do not become new internal dependencies.
- They are covered by a compatibility test only when external import behavior
  must remain stable.

For root graph wrappers, the allowed set remains
`rag_modules.graph_data_preparation` and `rag_modules.graph_indexing` unless
the manifest says otherwise. For repo-root `config.py`, only external callers
and compatibility checks may import it; internal modules and scripts should use
`rag_modules.configuration`.

## App And Runtime Legacy Attributes

Flat `system.*` and `runtime.*` compatibility attributes remain grouped behind
`GROUPED_LEGACY_ATTRIBUTE_MAP`. Public facades should delegate legacy lookup to
shared facade-support helpers. New explicit property methods for legacy names
should be prohibited; adding a compatibility attribute means adding one data
entry to the grouped map and proving it resolves through grouped views.

Canonical code should use grouped surfaces:

- `system.infrastructure`
- `system.retrieval`
- `system.services`
- matching grouped runtime views

This keeps compatibility behavior centralized and prevents flat attributes
from becoming the architecture again.

## Documentation

`docs/public_surface_retirement_plan.md` should be updated from a mixed plan
and history into a current policy document:

- list canonical packages;
- list remaining legacy bridges and their canonical targets;
- state the internal freeze rule;
- state the thin-wrapper rule;
- record retired facades in a compact history section;
- define the deletion criteria for the final retirement phase.

The documentation should avoid implying that internal callers may choose
between canonical and legacy imports.

## Testing

The closure should strengthen existing tests rather than add broad snapshot
tests.

Required checks:

- Manifest-driven expected public/service/internal/legacy module sets.
- Root legacy wrapper files exactly match manifest entries.
- Internal modules, scripts, and ordinary tests do not import legacy facades.
- Remaining legacy facades are thin wrappers with no local business logic.
- App/runtime flat legacy attributes are served only by the grouped map and
  facade-support delegation.
- Public bootstrapper facades remain delegation-only and do not reacquire
  lifecycle orchestration.

The focused verification command is:

```powershell
python -m pytest tests/test_public_api_manifest.py tests/test_public_surface_boundaries.py tests/test_bootstrap_facade_support.py tests/test_generation_integration_facade.py
```

If implementation touches a canonical package used by application assembly,
also run the corresponding app/runtime tests before completion.

## Non-Goals

This design does not remove the last external compatibility bridges in the
same change. It also does not redesign retrieval, generation, or graph runtime
behavior. The goal is boundary closure: canonical internal dependencies,
minimal legacy facades, and tests that make public-surface drift obvious.

## Completion Criteria

The work is complete when the repository can answer these questions from code
and tests:

- What is public API, service API, internal only, and legacy surface?
- Which canonical module owns each legacy bridge?
- Can any internal code accidentally depend on a legacy facade?
- Are legacy flat app/runtime attributes centralized in one data-driven map?
- Are public facades thin delegation layers rather than orchestration owners?

All answers should point to the manifest, the grouped legacy map, the policy
document, and focused boundary tests.

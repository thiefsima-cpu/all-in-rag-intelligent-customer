# Compatibility Layer Retirement Design

## Context

The repository already treats `/v1` as the preferred HTTP API surface for serving and
build clients. Existing unversioned HTTP routes remain available as compatibility
aliases. Separately, import-level legacy facades were retired in package version `0.2.0`,
but `rag_modules.routing.IntelligentQueryRouter` still exists as a thin adapter over
`RoutingWorkflowService`.

This slice closes the policy gap for those still-active compatibility layers without
changing runtime behavior.

## Goals

- Make the unversioned HTTP API alias retirement version explicit and testable.
- Make the `IntelligentQueryRouter` adapter retirement version explicit and testable.
- Keep current compatibility behavior stable while directing new clients to canonical
  surfaces.
- Document the difference between already-retired import facades, still-active HTTP
  aliases, and still-active service adapters.

## Non-Goals

- Removing unversioned HTTP routes in this slice.
- Removing `IntelligentQueryRouter` in this slice.
- Changing answer payload behavior, auth policy, request models, or build job semantics.
- Reopening the already-completed `0.2.0` import-facade retirement.

## Retirement Versions

The two active compatibility layers use different version clocks:

- Unversioned HTTP API aliases are removed in API version `2.0.0`.
- `IntelligentQueryRouter` is removed in package version `0.3.0`.

This split keeps HTTP contract migration tied to the API major version while keeping
Python service adapter cleanup tied to the package compatibility window.

## API Alias Policy

`rag_modules.interfaces.api.versioning` should remain the source for API version
constants and should add a machine-readable constant for the unversioned alias removal
version. The value should be reused by route descriptions and tests instead of copied as
free text.

Unversioned route behavior remains intact until API version `2.0.0`. OpenAPI should
continue to expose the old routes for discoverability during the migration window, but
the route metadata should mark them as deprecated compatibility aliases and point clients
to the matching `/v1` route.

The root health path `/` remains a special health compatibility endpoint and should be
documented separately from operational aliases. Framework/tooling paths such as
`/openapi.json`, `/docs`, `/redoc`, and `/metrics` remain outside the `/v1` namespace.

## Router Adapter Policy

`IntelligentQueryRouter` remains a thin adapter over `RoutingWorkflowService` until
package version `0.3.0`. It should not grow routing logic, trace state, fallback behavior,
or configuration ownership.

The adapter module should expose a machine-readable removal-version constant and mention
the canonical replacement in its docstring. Tests should continue to verify delegation to
the workflow service and should also assert the retirement metadata.

New internal code should prefer `RoutingWorkflowService` or the routing workflow protocol.
Compatibility tests may import `IntelligentQueryRouter` only to prove the adapter contract
and retirement metadata.

## Documentation Strategy

README should keep `/v1` as the recommended client surface and add the `2.0.0` removal
version for unversioned API aliases.

`docs/public_surface_retirement_plan.md` should keep the completed `0.2.0` import-facade
retirement as final state, then add a separate active compatibility section for:

- unversioned HTTP API aliases, removed in API version `2.0.0`;
- `rag_modules.routing.IntelligentQueryRouter`, removed in package version `0.3.0`.

This avoids mixing active compatibility adapters into the retired facade table.

## Testing Strategy

API tests should cover the compatibility policy rather than only route behavior:

- unversioned serving/build routes are still registered during the migration window;
- unversioned route OpenAPI operations are marked deprecated;
- unversioned route descriptions mention API version `2.0.0` and the canonical `/v1`
  route;
- `/v1` routes remain canonical and are not marked deprecated.

Router tests should cover:

- `IntelligentQueryRouter` still delegates to the injected workflow service;
- the adapter does not keep legacy mutable trace state;
- the adapter removal version is `0.3.0`;
- the adapter docstring names `RoutingWorkflowService` as the canonical replacement.

Documentation boundary tests should assert that README and the public-surface retirement
policy mention both active compatibility retirement versions.

## Acceptance Criteria

- Active compatibility layers have explicit removal-version constants.
- Tests fail if the removal versions drift from the documented policy.
- OpenAPI metadata steers clients away from unversioned routes without removing them.
- Documentation clearly separates completed `0.2.0` import-facade retirement from active
  compatibility layers.
- No production behavior changes before the planned retirement versions.

## Risks

Marking unversioned operations as deprecated in OpenAPI may surface warnings in generated
clients. That is intentional migration pressure and is safer than hiding or removing the
routes during the compatibility window.

Duplicating retirement version strings in docs and descriptions can drift. The
implementation should therefore use constants for code-generated text and tests should
verify the docs contain the same versions.

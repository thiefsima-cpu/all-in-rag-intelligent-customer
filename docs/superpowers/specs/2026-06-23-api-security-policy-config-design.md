# API Security Policy Configuration Design

## Goal

Make the HTTP management surfaces safe for enterprise production while keeping
local development ergonomic through explicit profile settings.

`/docs`, `/redoc`, `/openapi.json`, and `/metrics` should no longer be
unconditionally public. Production defaults should fail closed. Development
profiles can opt back into public documentation and scraper-friendly metrics.

## Scope

This design covers the FastAPI serving and build app factories, API security
middleware, API and observability configuration, tests, and operator
documentation.

It does not change answer, retrieval, graph, generation, build job execution,
or API request and response contracts beyond documentation and metrics access.

## Recommended Policy

Keep only infrastructure health probes public by default:

- `/`
- `/health`
- `/health/live`
- `/health/ready`

Protect or disable management surfaces by explicit configuration:

- `/docs` and `/redoc` are disabled by default.
- `/openapi.json` is disabled by default.
- `/metrics` is registered only when Prometheus export is enabled and requires
  API credentials by default.

The development profile should opt into convenience:

- Enable docs and OpenAPI.
- Make docs, OpenAPI, and metrics public for local tooling.

## Configuration

Add API settings:

- `docs_enabled: bool = false`
  - Controls Swagger UI and ReDoc registration.
- `openapi_enabled: bool = false`
  - Controls OpenAPI JSON registration.
- `docs_public: bool = false`
  - Allows unauthenticated access to docs routes when docs are enabled.
- `openapi_public: bool = false`
  - Allows unauthenticated access to OpenAPI JSON when OpenAPI is enabled.

Add observability setting:

- `prometheus_public: bool = false`
  - Allows unauthenticated access to `/metrics` when Prometheus export is
    enabled.

Add environment overrides:

- `API_DOCS_ENABLED`
- `API_OPENAPI_ENABLED`
- `API_DOCS_PUBLIC`
- `API_OPENAPI_PUBLIC`
- `PROMETHEUS_METRICS_PUBLIC`

`ENABLE_PROMETHEUS` keeps its existing meaning: whether the metrics endpoint is
registered at all.

## FastAPI App Factories

`create_serving_api_app` and `create_build_api_app` should pass FastAPI's
documentation URLs explicitly:

- `docs_url="/docs"` only when `api.docs_enabled` is true.
- `redoc_url="/redoc"` only when `api.docs_enabled` is true.
- `openapi_url="/openapi.json"` only when `api.openapi_enabled` is true.

The API settings must be resolved before constructing the FastAPI app so these
values are available at app creation time.

## Security Middleware

Replace the fixed `_PUBLIC_PATHS` dependency for management surfaces with a
small policy derived from settings:

- Base health paths stay public.
- Docs paths become public only when `docs_public` is true.
- OpenAPI JSON becomes public only when `openapi_public` is true.
- Metrics becomes public only when `observability.prometheus_public` is true.

Disabled docs or OpenAPI should return FastAPI's normal `404` because the
routes are not registered.

Authenticated access to enabled docs, OpenAPI, and metrics should still work
with the existing Bearer token or `X-API-Key` behavior.

## OpenAPI Security Schema

When authentication is enabled, `configure_openapi_security` should clear
operation-level security only for the currently public paths. If OpenAPI is
enabled but protected, the top-level security requirement remains visible in
the schema.

## Documentation

Update `docs/observability.md` to describe the two-step metrics policy:

- `ENABLE_PROMETHEUS=false` disables `/metrics`.
- `PROMETHEUS_METRICS_PUBLIC=false` keeps `/metrics` behind API credentials.

Update `.env.example` and `profiles/dev.toml` so local development remains
discoverable while the base profile is production-safe.

## Testing

Use focused tests:

- Defaults disable docs and OpenAPI.
- Enabled docs and OpenAPI require credentials by default.
- Docs and OpenAPI can be made public explicitly.
- Prometheus metrics require credentials by default.
- Metrics can be made public explicitly.
- `ENABLE_PROMETHEUS=false` leaves `/metrics` unregistered.
- Configuration loaders respect the new environment variables and profile
  defaults.
- OpenAPI security metadata clears security only for configured public paths.

## Acceptance Criteria

- Production defaults do not expose docs, OpenAPI, or metrics anonymously.
- Health probes remain public.
- Local development can opt into the previous convenience behavior through
  profile or environment configuration.
- Existing protected API credential behavior remains unchanged.
- Narrow API and configuration tests pass.

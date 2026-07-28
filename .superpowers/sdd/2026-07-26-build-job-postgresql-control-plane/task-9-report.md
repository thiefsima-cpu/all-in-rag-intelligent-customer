# Task 9 Report - Protected Build Job Audit API

## Status

Completed Task 9 from the approved PostgreSQL build-job control-plane plan.

## Delivered

- Added authenticated `GET /v1/jobs/{job_id}/events` with validated `limit` and opaque `cursor`.
- Added strict audit-event response models and response building through the Task 1 explicit
  `public_build_job_event` projection, followed by public-error sanitization.
- Added `BuildJobBackendUnavailableError` and its fixed `503 SERVICE_UNAVAILABLE` API mapping.
  Request-time `BuildJobRepositoryUnavailableError` is translated consistently for submit, list,
  get, cancel, retry, and audit-event listing; generic `BuildJobRepositoryError` is deliberately
  not translated to 503.
- Added API coverage for event pagination/cursor forwarding, idempotency-hash and lease-token
  redaction, invalid cursor (400), missing job (404), sanitized unavailable backend (503),
  protected authentication, and versioned OpenAPI routing.

## Verification

- `python -m pytest tests/test_api_build.py -k "audit" -q` - 3 passed (3 subtests passed).
- API/build/security/public, SSE, entrypoint, public-manifest, build-boundary, and type-ratchet
  test slices were run successfully.
- `python -m ruff format --check <Task 9 files>` - passed.
- `python -m ruff check <Task 9 files>` - passed.
- `python -m mypy --config-file pyproject.toml <Task 9 API modules>` - passed.
- The full pre-commit mypy hook passed. Its first all-files Ruff-format execution reformatted six
  unrelated pre-existing files; those formatting-only side effects were reverted to keep Task 9
  scoped.
- `python scripts/release_gate.py` - passed (69/69 cases).

## Scope Note

No live PostgreSQL service was required. The API tests use an injected fake build-job application,
and verify the unavailable-domain error contract without exposing its supplied secret.

## Fix Round 1

- Added explicit `ErrorResponseModel` response metadata for the audit route's 400, 404, and 503
  OpenAPI entries while retaining the operation-specific descriptions.
- Added regression coverage that verifies all three response schemas reference the stable error
  model and that the operation remains protected by the global security requirement.
- Extended audit tests to cover archived history availability when the current-job lookup is hidden,
  and parameterized unavailable backend coverage across submit, list, get, cancel, retry, and
  events. Each response is fixed `503 SERVICE_UNAVAILABLE` and excludes the injected secret.

# Task 10: Low-cardinality repository metrics

## Status

Complete.

## Implementation

- Added isolated Prometheus histogram/counters for build-job repository operation latency,
  claims, classified errors, and retention work.
- Restricted every repository metric label to a fixed allowlist. Unsafe, unrecognised, or
  high-cardinality values normalize to `unknown`.
- Added `PostgresBuildJobObservers` and a uniform `perf_counter` operation wrapper. Observer
  failures are ignored so telemetry cannot change repository behaviour.
- Bound the observers from runtime telemetry during PostgreSQL composition, before construction,
  so pool-open and schema-verification failures are observable without exposing DSNs, SQL, IDs,
  tokens, SQLSTATE strings, or exception text.
- Recorded archive counts from the database cursor row count and purge counts from the bounded
  selected archive batch. Diagnostics distinguish `ready` and `not_ready` operation outcomes.

## Verification

- `python -m pytest tests/test_runtime_telemetry.py tests/test_postgres_build_job_repository.py tests/test_build_job_composition.py tests/test_api_build.py -q`
  - 99 passed, 16 skipped, 9 subtests passed.
- `python -m pytest tests/test_api_build.py tests/test_api_public_surface.py tests/test_api_security.py -k "diagnostic or build_job" -q`
  - 28 passed, 44 deselected, 9 subtests passed.
- `ruff check` and `ruff format --check` for all changed sources/tests.
- `mypy rag_modules/telemetry.py rag_modules/runtime/build_jobs/postgres/repository.py rag_modules/app/composition/build_jobs.py`
- `python scripts/release_gate.py`
  - 69/69 cases passed.

## Gate note

- The focused ratchet suite has one failure in the repository-wide explicit-`Any` baseline
  (`175` observed versus `174` approved). This task does not add an `Any` occurrence; the changed
  production files retain their pre-existing telemetry `Any` annotations only. The offline release
  gate passes.
